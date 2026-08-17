/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Layout } from "@web/search/layout";
import { _t } from "@web/core/l10n/translation";
import { formatMonetary } from "@web/views/fields/formatters";

export class VasDebtAging extends Component {
    static template = "connecta_vas.VasDebtAging";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const ctx = this.props.action.context || {};
        this.kind = ctx.vas_aging_kind || "ar";
        this.state = useState({
            loading: true,
            error: false,
            data: null,
            periods: [],
            periodId: false,
        });
        onWillStart(async () => {
            await this.loadPeriods();
            await this.reload();
        });
    }

    async loadPeriods() {
        const opts = await this.orm.call("vas.dashboard", "get_period_options", []);
        this.state.periods = opts.periods || [];
        this.state.periodId = opts.default_period_id || false;
    }

    async reload() {
        this.state.loading = true;
        this.state.error = false;
        try {
            if (!this.state.periodId) {
                this.state.error = _t("Chưa có kỳ kế toán có số liệu.");
                this.state.data = null;
                return;
            }
            const data = await this.orm.call("vas.debt.aging", "get_aging_report", [
                this.state.periodId,
                this.kind,
            ]);
            if (data?.error) {
                this.state.error = data.error;
                this.state.data = null;
            } else {
                this.state.data = data;
            }
        } catch (e) {
            this.state.error = e.message || String(e);
            this.state.data = null;
        } finally {
            this.state.loading = false;
        }
    }

    async onPeriodChange(ev) {
        const raw = ev.currentTarget?.value;
        this.state.periodId = raw ? parseInt(raw, 10) : false;
        await this.reload();
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
}

registry.category("actions").add("vas_debt_aging", VasDebtAging);
