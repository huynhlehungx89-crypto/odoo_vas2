/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Layout } from "@web/search/layout";
import { _t } from "@web/core/l10n/translation";
import { formatMonetary } from "@web/views/fields/formatters";

export class VasCostingM5 extends Component {
    static template = "connecta_vas.VasCostingM5";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const ctx = this.props.action.context || {};
        this.periodId = ctx.vas_costing_period_id || ctx.active_id || false;
        this.state = useState({
            loading: true,
            error: false,
            data: null,
            activeTab: false,
        });
        onWillStart(async () => {
            await this.reload();
        });
    }

    async reload() {
        this.state.loading = true;
        this.state.error = false;
        try {
            if (!this.periodId) {
                this.state.error = _t("Thiếu kỳ tính giá thành.");
                this.state.data = null;
                return;
            }
            const data = await this.orm.call("vas.costing.period", "get_m5_payload", [
                this.periodId,
            ]);
            if (data?.error) {
                this.state.error = data.error;
                this.state.data = null;
            } else {
                this.state.data = data;
                const tabs = data.tabs || [];
                this.state.activeTab = tabs.length ? tabs[0].key : false;
            }
        } catch (e) {
            this.state.error = e.message || String(e);
            this.state.data = null;
        } finally {
            this.state.loading = false;
        }
    }

    formatMoney(amount) {
        if (amount === false || amount === undefined || amount === null) {
            return "—";
        }
        const currencyId = this.state.data?.currency_id;
        try {
            return formatMonetary(amount, { currencyId });
        } catch {
            return Number(amount).toLocaleString("vi-VN");
        }
    }

    cellAmount(row, colId) {
        if (!row || !row.cells) {
            return false;
        }
        return row.cells[String(colId)];
    }

    get activeTabData() {
        const tabs = this.state.data?.tabs || [];
        return tabs.find((t) => t.key === this.state.activeTab) || false;
    }

    onSelectTab(key) {
        this.state.activeTab = key;
    }

    onSelectTabClick(ev) {
        const key = ev.currentTarget?.dataset?.tabKey;
        if (key) {
            this.state.activeTab = key;
        }
    }

    async onBackToList() {
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Kỳ tính giá thành"),
            res_model: "vas.costing.period",
            view_mode: "list,form",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    async onOpenPeriodForm() {
        const act = await this.orm.call("vas.costing.period", "action_open_period_form", [
            [this.periodId],
        ]);
        if (act) {
            await this.action.doAction(act);
        }
    }

    async onOpenObject(costObjectId) {
        if (!costObjectId) {
            return;
        }
        const act = await this.orm.call(
            "vas.costing.period",
            "action_open_s18_report_for_object",
            [[this.periodId], costObjectId],
        );
        if (act) {
            await this.action.doAction(act);
        }
    }

    async onOpenObjectClick(ev) {
        const raw = ev.currentTarget?.dataset?.costObjectId;
        const id = raw ? parseInt(raw, 10) : false;
        if (id) {
            await this.onOpenObject(id);
        }
    }
}

registry.category("actions").add("vas_costing_m5", VasCostingM5);
