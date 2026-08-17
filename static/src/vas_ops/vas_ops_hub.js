/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Layout } from "@web/search/layout";
import { _t } from "@web/core/l10n/translation";

export class VasOpsHub extends Component {
    static template = "connecta_vas.VasOpsHub";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            tiles: [],
            error: false,
        });
        onWillStart(async () => {
            try {
                this.state.tiles = await this.orm.call("vas.ops.group", "get_hub_tiles", []);
            } catch (e) {
                this.state.error = e.message || String(e);
            } finally {
                this.state.loading = false;
            }
        });
    }

    async onSync() {
        const act = await this.orm.call("vas.ops.group", "action_sync_now", []);
        if (act) {
            await this.action.doAction(act);
        }
    }

    async onTileClick(tile) {
        const act = await this.orm.call("vas.ops.group", "action_open_from_hub", [tile.id]);
        if (act) {
            await this.action.doAction(act);
        }
    }
}

registry.category("actions").add("vas_ops_hub", VasOpsHub);
