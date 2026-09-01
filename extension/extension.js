/* ArchClip -- ponte entre o GNOME Shell e o daemon.
 *
 * O Mutter não implementa data-control (nem `wlr-data-control-unstable-v1`
 * nem `ext-data-control-v1`): é decisão de projeto do GNOME, porque esses
 * protocolos deixam qualquer cliente ler tudo o que você copia. Sem eles,
 * `wl-paste --watch` falha e um processo comum só enxerga a seleção enquanto
 * tem foco de teclado -- inútil para um daemon em segundo plano.
 *
 * Código rodando dentro do Shell não tem essa limitação: o MetaSelection é o
 * dono da seleção. Esta extensão publica na sessão o serviço
 * io.github.theuszma.ArchClip.Shell, com o mínimo necessário para o daemon
 * fazer o trabalho dele:
 *
 *   SelectionChanged(as)      sinal: a seleção mudou, estes são os tipos MIME
 *   GetMimetypes() -> as      tipos MIME da seleção atual
 *   GetSelection(s) -> ay     conteúdo da seleção em um tipo MIME
 *   SetSelection(s, ay)       põe conteúdo na seleção (colar do histórico)
 *   SetWindowAbove(b)         mantém a janela do ArchClip por cima das outras
 *
 * O sinal carrega só a lista de tipos, nunca o conteúdo: quem quiser o dado
 * precisa pedir. Toda decisão sobre o que guardar (texto x imagem, tamanho
 * máximo, dica de gerenciador de senha) fica no daemon, que é quem tem a
 * configuração do usuário.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.theuszma.ArchClip.Shell';
const OBJECT_PATH = '/io/github/theuszma/ArchClip/Shell';

// Só janelas do ArchClip podem ser levantadas por aqui. Um serviço que
// pusesse qualquer janela por cima seria um brinquedo para qualquer processo
// da sessão -- e não é para isso que ele existe.
const APP_ID = 'io.github.theuszma.ArchClip';

// Uma troca de seleção costuma disparar `owner-changed` mais de uma vez (o
// dono antigo sai, o novo entra). Agrupamos os eventos próximos para não
// mandar o daemon ler duas vezes a mesma coisa.
const SETTLE_MS = 60;

// A transferência acontece dentro do processo do Shell. O daemon tem o
// próprio limite, bem menor (`max_item_size_mb`); este teto existe só para
// uma seleção absurda não inchar a memória do Shell.
const MAX_BYTES = 64 * 1024 * 1024;

// Se o aplicativo que publicou a seleção não responder, a transferência fica
// pendurada -- e com ela a chamada D-Bus do daemon. Cancelamos antes disso.
const TRANSFER_TIMEOUT_S = 10;

const INTERFACE = `
<node>
  <interface name="io.github.theuszma.ArchClip.Shell">
    <method name="GetMimetypes">
      <arg type="as" direction="out" name="mimetypes"/>
    </method>
    <method name="GetSelection">
      <arg type="s" direction="in" name="mimetype"/>
      <arg type="ay" direction="out" name="content"/>
    </method>
    <method name="SetSelection">
      <arg type="s" direction="in" name="mimetype"/>
      <arg type="ay" direction="in" name="content"/>
    </method>
    <method name="SetWindowAbove">
      <arg type="b" direction="in" name="above"/>
    </method>
    <signal name="SelectionChanged">
      <arg type="as" name="mimetypes"/>
    </signal>
  </interface>
</node>`;

export default class ArchClipExtension extends Extension {
    enable() {
        this._selection = global.display.get_selection();
        this._settleId = 0;
        this._transfers = new Set();

        this._dbus = Gio.DBusExportedObject.wrapJSObject(INTERFACE, this);
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);
        this._nameId = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            null,
            null,
            null
        );

        this._ownerChangedId = this._selection.connect(
            'owner-changed',
            (_selection, type) => this._onOwnerChanged(type)
        );

        // A janela do histórico some e volta o tempo todo, e cada vez que
        // volta é uma MetaWindow nova -- por isso o estado fica aqui, e não
        // numa chamada avulsa que o daemon teria de repetir.
        this._keepAbove = false;
        this._windowCreatedId = global.display.connect(
            'window-created',
            (_display, window) => {
                if (this._keepAbove && this._isOurWindow(window))
                    window.make_above();
            }
        );
    }

    disable() {
        // O Shell mantém o módulo carregado até o fim da sessão, então é este
        // método -- e não o descarregamento -- que tira o serviço do ar
        // quando o usuário desliga a extensão.
        if (this._settleId) {
            GLib.Source.remove(this._settleId);
            this._settleId = 0;
        }
        if (this._ownerChangedId) {
            this._selection.disconnect(this._ownerChangedId);
            this._ownerChangedId = 0;
        }
        if (this._windowCreatedId) {
            global.display.disconnect(this._windowCreatedId);
            this._windowCreatedId = 0;
        }
        // Deixar uma janela presa acima de todas depois de desligar a
        // extensão seria um estrago sem dono: ninguém mais poderia desfazer.
        this._eachOurWindow(window => window.unmake_above());
        this._keepAbove = false;
        for (const cancellable of this._transfers ?? [])
            cancellable.cancel();
        this._transfers = null;
        if (this._nameId) {
            Gio.bus_unown_name(this._nameId);
            this._nameId = 0;
        }
        if (this._dbus) {
            this._dbus.unexport();
            this._dbus = null;
        }
        this._selection = null;
    }

    // ------------------------------------------------------------ vigilância

    _onOwnerChanged(type) {
        if (type !== Meta.SelectionType.SELECTION_CLIPBOARD)
            return;

        if (this._settleId)
            GLib.Source.remove(this._settleId);

        this._settleId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, SETTLE_MS, () => {
            this._settleId = 0;
            if (this._dbus) {
                this._dbus.emit_signal(
                    'SelectionChanged',
                    new GLib.Variant('(as)', [this._mimetypes()])
                );
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    _mimetypes() {
        if (!this._selection)
            return [];
        return this._selection.get_mimetypes(Meta.SelectionType.SELECTION_CLIPBOARD);
    }

    // ---------------------------------------------------------------- D-Bus

    GetMimetypes() {
        return this._mimetypes();
    }

    GetSelectionAsync([mimetype], invocation) {
        // Assíncrono de propósito: a transferência conversa com o processo
        // que publicou a seleção, e um método síncrono aqui congelaria o
        // Shell inteiro enquanto o outro lado não respondesse.
        if (!this._selection) {
            invocation.return_error_literal(
                Gio.DBusError, Gio.DBusError.FAILED, 'extensão desligada');
            return;
        }

        const stream = Gio.MemoryOutputStream.new_resizable();
        const cancellable = new Gio.Cancellable();
        this._transfers.add(cancellable);

        let timeoutId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, TRANSFER_TIMEOUT_S, () => {
                timeoutId = 0;
                cancellable.cancel();
                return GLib.SOURCE_REMOVE;
            });

        const done = () => {
            this._transfers?.delete(cancellable);
            if (timeoutId) {
                GLib.Source.remove(timeoutId);
                timeoutId = 0;
            }
        };

        this._selection.transfer_async(
            Meta.SelectionType.SELECTION_CLIPBOARD,
            mimetype,
            -1,
            stream,
            cancellable,
            (selection, result) => {
                done();

                let bytes;
                try {
                    selection.transfer_finish(result);
                    stream.close(null);
                    bytes = stream.steal_as_bytes();
                } catch (error) {
                    invocation.return_error_literal(
                        Gio.DBusError,
                        Gio.DBusError.FAILED,
                        `transferência de ${mimetype} falhou: ${error.message}`
                    );
                    return;
                }

                if (bytes.get_size() > MAX_BYTES) {
                    invocation.return_error_literal(
                        Gio.DBusError,
                        Gio.DBusError.LIMITS_EXCEEDED,
                        `seleção grande demais: ${bytes.get_size()} bytes`
                    );
                    return;
                }

                invocation.return_value(
                    new GLib.Variant('(ay)', [bytes.get_data() ?? new Uint8Array(0)])
                );
            }
        );
    }

    SetWindowAbove(above) {
        this._keepAbove = above;
        this._eachOurWindow(window => {
            if (above)
                window.make_above();
            else
                window.unmake_above();
        });
    }

    _isOurWindow(window) {
        if (!window)
            return false;
        if (window.get_gtk_application_id() === APP_ID)
            return true;
        // O gtk_application_id só existe para janelas GTK já registradas; o
        // wm_class serve de rede de segurança enquanto isso não acontece.
        return (window.get_wm_class() ?? '').toLowerCase() === APP_ID.toLowerCase();
    }

    _eachOurWindow(callback) {
        for (const actor of global.get_window_actors()) {
            const window = actor.meta_window;
            if (this._isOurWindow(window))
                callback(window);
        }
    }

    SetSelection(mimetype, content) {
        // Quem passa a ser dono da seleção é o Shell, não o daemon -- então o
        // conteúdo continua colável mesmo se o ArchClip for encerrado.
        const source = Meta.SelectionSourceMemory.new(mimetype, new GLib.Bytes(content));
        this._selection.set_owner(Meta.SelectionType.SELECTION_CLIPBOARD, source);
    }
}
