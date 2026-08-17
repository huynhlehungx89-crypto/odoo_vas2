/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { RPCError } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Layout } from "@web/search/layout";
import { _t } from "@web/core/l10n/translation";

/** UserError / ValidationError từ server — hiện cảnh báo, không bật dialog Odoo Server Error. */
function rpcErrorMessage(error) {
    if (error instanceof RPCError) {
        return error.data?.message || error.message || String(error);
    }
    return error?.message || String(error);
}

function rpcErrorKind(error) {
    if (
        error instanceof RPCError
        && error.exceptionName
        && /UserError|ValidationError|AccessError/.test(error.exceptionName)
    ) {
        return "warning";
    }
    return "danger";
}

/**
 * Khung báo cáo VAS dùng chung (OWL).
 * Chỉ vẽ meta + columns + lines từ get_report_data(options).
 * Pha 2: xổ/thu theo parent_id, lọc account, look native.
 */
export class VasReportClient extends Component {
    static template = "connecta_vas.VasReportClient";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const ctx = this.props.action.context || {};
        this.reportModel = ctx.report_model || "vas.trial.balance.wizard";
        this.reportTitle = ctx.report_title || _t("Báo cáo VAS");
        this.requiresAccount = Boolean(ctx.requires_account);
        this.ctxSnapshotId = ctx.snapshot_id || false;
        this.ctxPeriodFrom = ctx.period_from_id || false;
        this.ctxPeriodTo = ctx.period_to_id || false;
        this.ctxHideReversed =
            ctx.hide_reversed === undefined ? null : Boolean(ctx.hide_reversed);
        this.ctxCompanyId = ctx.company_id || false;

        this.state = useState({
            loading: true,
            loaded: false,
            error: false,
            errorKind: "danger",
            periods: [],
            accounts: [],
            options: {
                company_id: false,
                period_from_id: false,
                period_to_id: false,
                account_id: false,
                hide_reversed: true,
                snapshot_id: false,
            },
            data: {
                meta: {},
                columns: [],
                lines: [],
                checks: {},
            },
            unfoldedIds: {},
        });

        onWillStart(async () => {
            await this.loadFilters();
            // Chỉ tự tải khi mở bản đã lập (snapshot_id) — menu chính chờ bấm Xem.
            if (this.ctxSnapshotId) {
                await this.reload();
            } else {
                this.state.loading = false;
            }
        });
    }

    get needsAccount() {
        return (
            this.requiresAccount ||
            Boolean(this.state.data.meta?.requires_account)
        );
    }

    async loadFilters() {
        const defaults = await this.orm.call("vas.report.engine", "get_filter_defaults", []);
        this.state.periods = defaults.periods || [];
        this.state.accounts = defaults.accounts || [];
        this.state.options = {
            company_id: this.ctxCompanyId || defaults.company_id,
            period_from_id: this.ctxPeriodFrom || defaults.period_from_id,
            period_to_id: this.ctxPeriodTo || defaults.period_to_id,
            account_id: defaults.account_id || false,
            hide_reversed:
                this.ctxHideReversed === null
                    ? defaults.hide_reversed
                    : this.ctxHideReversed,
            snapshot_id: this.ctxSnapshotId || false,
        };
    }

    async reload() {
        if (this.needsAccount && !this.state.options.account_id) {
            this.notification.add(_t("Chọn tài khoản trước khi xem sổ."), { type: "warning" });
            return;
        }
        if (!this.state.options.period_from_id || !this.state.options.period_to_id) {
            this.notification.add(_t("Chọn Từ kỳ và Đến kỳ trước khi xem báo cáo."), {
                type: "warning",
            });
            return;
        }
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.orm.silent.call(
                this.reportModel,
                "get_report_data",
                [{ ...this.state.options }]
            );
            this.state.data = data;
            this.state.loaded = true;
            // Giữ trạng thái xổ đã mở nếu vẫn còn id; mặc định theo line.unfolded
            const next = { ...this.state.unfoldedIds };
            for (const line of data.lines || []) {
                if (line.unfoldable && next[line.id] === undefined) {
                    next[line.id] = Boolean(line.unfolded);
                }
            }
            this.state.unfoldedIds = next;
        } catch (e) {
            const msg = rpcErrorMessage(e);
            const kind = rpcErrorKind(e);
            this.state.error = msg;
            this.state.errorKind = kind;
            this.state.loaded = false;
            this.notification.add(msg, { type: kind });
        } finally {
            this.state.loading = false;
        }
    }

    _clearReportView() {
        this.state.loaded = false;
        this.state.error = false;
        this.state.data = { meta: {}, columns: [], lines: [], checks: {} };
        this.state.unfoldedIds = {};
    }

    onPeriodFromChange(ev) {
        this.state.options.period_from_id = Number(ev.target.value) || false;
        this.state.options.snapshot_id = false;
        this._clearReportView();
    }

    onPeriodToChange(ev) {
        this.state.options.period_to_id = Number(ev.target.value) || false;
        this.state.options.snapshot_id = false;
        this._clearReportView();
    }

    onAccountChange(ev) {
        this.state.options.account_id = Number(ev.target.value) || false;
        this._clearReportView();
    }

    onHideReversedChange(ev) {
        this.state.options.hide_reversed = Boolean(ev.target.checked);
        this.state.options.snapshot_id = false;
        this._clearReportView();
    }

    async onClickRefresh() {
        await this.reload();
    }

    async onClickXlsx() {
        try {
            const action = await this.orm.silent.call(
                this.reportModel,
                "action_export_xlsx_options",
                [{ ...this.state.options }]
            );
            if (action) {
                await this.action.doAction(action);
            }
        } catch (e) {
            this.notification.add(rpcErrorMessage(e), { type: rpcErrorKind(e) });
        }
    }

    async onClickPdf() {
        try {
            const action = await this.orm.silent.call(
                this.reportModel,
                "action_export_pdf_options",
                [{ ...this.state.options }]
            );
            if (action) {
                await this.action.doAction(action);
            }
        } catch (e) {
            this.notification.add(rpcErrorMessage(e), { type: rpcErrorKind(e) });
        }
    }

    toggleUnfold(lineId) {
        this.state.unfoldedIds = {
            ...this.state.unfoldedIds,
            [lineId]: !this.state.unfoldedIds[lineId],
        };
    }

    isUnfolded(line) {
        if (!line.unfoldable) {
            return false;
        }
        if (this.state.unfoldedIds[line.id] !== undefined) {
            return Boolean(this.state.unfoldedIds[line.id]);
        }
        return Boolean(line.unfolded);
    }

    formatCell(value, col) {
        if (value === false || value === null || value === undefined || value === "") {
            return "";
        }
        if (value === "N/A") {
            return "N/A";
        }
        // Mã kỹ thuật nội bộ: V.1.total → V.1 (cột mã / thuyết minh trên màn xem)
        if (
            col.display === "note_ref"
            || col.name === "note_b09"
            || col.name === "code"
        ) {
            return String(value).replace(/\.(total|detail|opening|closing)$/i, "");
        }
        if (col.type === "monetary") {
            const n = Number(value);
            if (Number.isNaN(n)) {
                return String(value);
            }
            // Kiểu Việt Nam giống F01: 20.914.500 (không dấu phẩy, không .00)
            const abs = Math.abs(n).toLocaleString("vi-VN", {
                maximumFractionDigits: 0,
                minimumFractionDigits: 0,
            });
            if (col.negative_paren && n < 0) {
                return `(${abs})`;
            }
            if (n < 0) {
                return `-${abs}`;
            }
            return abs;
        }
        return String(value);
    }

    cellClass(value, col) {
        const classes = [];
        if (col.align === "right") {
            classes.push("text-end");
        }
        if (value === "N/A") {
            classes.push("text-danger", "fw-semibold");
            return classes.join(" ");
        }
        if (col.type === "monetary") {
            const n = Number(value) || 0;
            if (!n) {
                classes.push("o_vas_muted");
            } else if (n < 0) {
                classes.push("o_vas_negative");
            }
        }
        return classes.join(" ");
    }

    lineClass(line) {
        const classes = [];
        if (line.is_total) {
            classes.push("o_vas_report_total", "fw-bold");
        }
        if (line.is_section || line.unfoldable) {
            classes.push("o_vas_section");
        }
        if (this.isUnfolded(line)) {
            classes.push("o_vas_unfolded", "fw-bold");
        }
        if (line.class) {
            classes.push(line.class);
        }
        return classes.join(" ");
    }

    get visibleLines() {
        const lines = this.state.data.lines || [];
        const byId = Object.fromEntries(lines.map((l) => [l.id, l]));
        const visible = [];
        for (const line of lines) {
            let parentId = line.parent_id;
            let hidden = false;
            while (parentId) {
                const parent = byId[parentId];
                if (!parent) {
                    break;
                }
                if (parent.unfoldable && !this.isUnfolded(parent)) {
                    hidden = true;
                    break;
                }
                parentId = parent.parent_id;
            }
            if (!hidden) {
                visible.push(line);
            }
        }
        return visible;
    }

    get displayName() {
        return this.state.data.meta?.title || this.reportTitle;
    }
}

registry.category("actions").add("vas_report_client", VasReportClient);
