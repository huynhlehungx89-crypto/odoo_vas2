/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Layout } from "@web/search/layout";
import { _t } from "@web/core/l10n/translation";

export class VasOpsWorkflow extends Component {
    static template = "connecta_vas.VasOpsWorkflow";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const ctx = this.props.action.context || {};
        this.groupCode = ctx.vas_ops_group_code || "cash";
        this.state = useState({
            loading: true,
            payload: {
                group: false,
                layout: "empty",
                message: "",
                process: [],
                detached: [],
                catalog: [],
                report: [],
            },
            expandedId: false,
            error: false,
        });
        onWillStart(async () => {
            await this.reload();
        });
    }

    async reload() {
        this.state.loading = true;
        try {
            this.state.payload = await this.orm.call(
                "vas.ops.group",
                "get_workflow_payload",
                [this.groupCode],
            );
            this.state.error = false;
        } catch (e) {
            this.state.error = e.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    get title() {
        return this.state.payload.group?.name || _t("Nghiệp vụ");
    }

    async onSync() {
        const act = await this.orm.call("vas.ops.group", "action_sync_now", []);
        if (act) {
            await this.action.doAction(act);
        }
    }

    async openXmlid(xmlid) {
        if (!xmlid) {
            return;
        }
        const act = await this.orm.call("vas.ops.group", "action_open_xmlid", [xmlid]);
        if (act) {
            await this.action.doAction(act);
        }
    }

    onProcessClick(btn) {
        if (btn.is_choice_parent) {
            this.state.expandedId = this.state.expandedId === btn.id ? false : btn.id;
            return;
        }
        if (btn.has_action && btn.action_xmlid) {
            this.openXmlid(btn.action_xmlid);
        }
    }

    onChildClick(child) {
        if (child.has_action && child.action_xmlid) {
            this.openXmlid(child.action_xmlid);
        }
    }

    async onSeeAllReports() {
        await this.openXmlid("connecta_vas.action_vas_trial_balance_client");
    }
}

registry.category("actions").add("vas_ops_workflow", VasOpsWorkflow);
