/** @odoo-module **/

import { Component, onWillStart, useEffect, useRef, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Layout } from "@web/search/layout";
import { _t } from "@web/core/l10n/translation";
import { formatMonetary } from "@web/views/fields/formatters";

export class VasDashboard extends Component {
    static template = "connecta_vas.VasDashboard";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.pnlCanvas = useRef("pnlChart");
        this.cashCanvas = useRef("cashChart");
        this.costCanvas = useRef("costChart");
        this.charts = { pnl: null, cash: null, cost: null };
        this.state = useState({
            loading: true,
            error: false,
            periods: [],
            periodId: false,
            data: null,
            chartReady: false,
        });
        onWillStart(async () => {
            try {
                await loadBundle("web.chartjs_lib");
                this.state.chartReady = typeof Chart !== "undefined";
                const opts = await this.orm.call("vas.dashboard", "get_period_options", []);
                this.state.periods = opts.periods || [];
                this.state.periodId = opts.default_period_id || false;
                await this.reload();
            } catch (e) {
                this.state.error = e.message || String(e);
                this.state.loading = false;
            }
        });
        useEffect(
            () => {
                this.renderCharts();
                return () => this.destroyCharts();
            },
            () => [this.state.data, this.state.chartReady, this.state.loading],
        );
    }

    async reload() {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call("vas.dashboard", "get_dashboard_data", [
                this.state.periodId || false,
                true,
            ]);
            if (this.state.data?.error) {
                this.state.error = this.state.data.error;
            }
            if (this.state.data?.period_id) {
                this.state.periodId = this.state.data.period_id;
            }
        } catch (e) {
            this.state.error = e.message || String(e);
            this.state.data = null;
        } finally {
            this.state.loading = false;
        }
    }

    async onPeriodChange(ev) {
        const val = ev.target.value;
        this.state.periodId = val ? parseInt(val, 10) : false;
        await this.reload();
    }

    formatMoney(amount) {
        const currencyId = this.state.data?.currency_id;
        if (amount === false || amount === undefined || amount === null) {
            return "—";
        }
        try {
            return formatMonetary(amount, { currencyId });
        } catch {
            return Number(amount).toLocaleString("vi-VN");
        }
    }

    destroyCharts() {
        for (const key of Object.keys(this.charts)) {
            if (this.charts[key]) {
                this.charts[key].destroy();
                this.charts[key] = null;
            }
        }
    }

    renderCharts() {
        this.destroyCharts();
        if (!this.state.chartReady || !this.state.data || this.state.loading) {
            return;
        }
        const tiles = this.state.data.tiles || {};
        this._renderPnlChart(tiles.pnl);
        this._renderCashChart(tiles.cashflow);
        this._renderCostChart(tiles.cost_structure);
    }

    _renderPnlChart(tile) {
        if (!tile || tile.empty || !tile.months?.length || !this.pnlCanvas.el) {
            return;
        }
        const labels = tile.months.map((m) => m.label);
        this.charts.pnl = new Chart(this.pnlCanvas.el, {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        label: _t("Doanh thu"),
                        data: tile.months.map((m) => m.revenue),
                        backgroundColor: "rgba(37, 99, 235, 0.7)",
                    },
                    {
                        label: _t("Chi phí"),
                        data: tile.months.map((m) => m.expense),
                        backgroundColor: "rgba(220, 38, 38, 0.65)",
                    },
                    {
                        label: _t("Lợi nhuận"),
                        data: tile.months.map((m) => m.profit),
                        backgroundColor: "rgba(22, 163, 74, 0.7)",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
                scales: { y: { beginAtZero: true } },
            },
        });
    }

    _renderCashChart(tile) {
        if (!tile || tile.empty || !tile.months?.length || !this.cashCanvas.el) {
            return;
        }
        this.charts.cash = new Chart(this.cashCanvas.el, {
            type: "bar",
            data: {
                labels: tile.months.map((m) => m.label),
                datasets: [
                    {
                        label: _t("Thu"),
                        data: tile.months.map((m) => m.inflow),
                        backgroundColor: "rgba(22, 163, 74, 0.7)",
                    },
                    {
                        label: _t("Chi"),
                        data: tile.months.map((m) => m.outflow),
                        backgroundColor: "rgba(220, 38, 38, 0.65)",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "bottom" } },
                scales: { y: { beginAtZero: true } },
            },
        });
    }

    _renderCostChart(tile) {
        if (!tile || tile.empty || !tile.slices?.length || !this.costCanvas.el) {
            return;
        }
        const colors = tile.slices.map((_, i) => {
            const hue = (i * 47) % 360;
            return `hsl(${hue} 55% 45%)`;
        });
        this.charts.cost = new Chart(this.costCanvas.el, {
            type: "pie",
            data: {
                labels: tile.slices.map((s) => s.label),
                datasets: [
                    {
                        data: tile.slices.map((s) => Math.abs(s.amount)),
                        backgroundColor: colors,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "right" } },
            },
        });
    }

    async onOpenGeneral() {
        const act = await this.orm.call("vas.dashboard", "action_open_general_workflow", []);
        if (act) {
            await this.action.doAction(act);
        }
    }
}

registry.category("actions").add("vas_dashboard", VasDashboard);
