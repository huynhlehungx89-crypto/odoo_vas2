# -*- coding: utf-8 -*-
"""M5 — màn hình kết quả kỳ tính giá thành (chỉ đọc kết quả đã lưu / hàm engine)."""
from collections import defaultdict
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero, float_round


class VasCostingPeriodM5(models.Model):
    _inherit = 'vas.costing.period'

    # Cột list — Float (không Monetary): False → ô trống, tránh 0 giả khi chưa tính.
    m5_opening_wip = fields.Float(
        string='Dở dang đầu kỳ', digits=(16, 2),
        compute='_compute_m5_list_amounts',
    )
    m5_period_incurred = fields.Float(
        string='Phát sinh trong kỳ', digits=(16, 2),
        compute='_compute_m5_list_amounts',
    )
    m5_cost_reduction = fields.Float(
        string='Khoản giảm giá thành', digits=(16, 2),
        compute='_compute_m5_list_amounts',
    )
    m5_closing_wip = fields.Float(
        string='Dở dang cuối kỳ', digits=(16, 2),
        compute='_compute_m5_list_amounts',
    )
    m5_total_cost = fields.Float(
        string='Tổng giá thành', digits=(16, 2),
        compute='_compute_m5_list_amounts',
    )
    m5_has_result = fields.Boolean(
        string='Đã có kết quả', compute='_compute_m5_list_amounts',
    )

    @api.depends(
        'current_result_id',
        'current_result_id.opening_wip',
        'current_result_id.amount_direct',
        'current_result_id.amount_overhead',
        'current_result_id.amount_reduction',
        'current_result_id.closing_wip',
        'current_result_id.total_cost',
    )
    def _compute_m5_list_amounts(self):
        for period in self:
            ver = period.current_result_id
            if not ver:
                period.m5_has_result = False
                period.m5_opening_wip = False
                period.m5_period_incurred = False
                period.m5_cost_reduction = False
                period.m5_closing_wip = False
                period.m5_total_cost = False
                continue
            period.m5_has_result = True
            period.m5_opening_wip = ver.opening_wip
            # Cùng cách engine ghi period.period_incurred lúc tính
            period.m5_period_incurred = float_round(
                (ver.amount_direct or 0.0) + (ver.amount_overhead or 0.0), 2,
            )
            period.m5_cost_reduction = ver.amount_reduction
            period.m5_closing_wip = ver.closing_wip
            period.m5_total_cost = ver.total_cost

    def get_formview_action(self, *args, **kwargs):
        """Bấm một dòng kỳ → M5 (không mở form lồng tab)."""
        self.ensure_one()
        return self.action_open_m5()

    def action_open_m5(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'vas_costing_m5',
            'name': _('Kết quả kỳ — %s') % (self.name or ''),
            'context': {
                'vas_costing_period_id': self.id,
            },
        }

    def action_open_period_form(self):
        """Từ M5 → biểu mẫu kỳ (tính / duyệt) — giữ đường quay lại."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': 'vas.costing.period',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(
                self.env.ref('connecta_vas.view_vas_costing_period_form').id,
                'form',
            )],
            'target': 'current',
        }

    def action_open_s18_report_for_object(self, cost_object_id):
        """Nút trong M5 → thẻ S18 một đối tượng qua vas_report_client."""
        self.ensure_one()
        ver = self.current_result_id
        if not ver:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Chưa có kết quả'),
                    'message': _('Kỳ chưa có phiên bản kết quả hiệu lực.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        line = ver.line_ids.filtered(
            lambda l: l.cost_object_id.id == cost_object_id,
        )[:1]
        if not line:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Không có dòng'),
                    'message': _('Không tìm thấy kết quả đã lưu cho đối tượng này.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'vas_report_client',
            'name': _('Thẻ S18 — %s') % (line.cost_object_id.display_name or ''),
            'context': {
                'report_model': 'vas.costing.result.line',
                'report_title': _('Thẻ tính giá thành S18-DNN'),
                # Khung OWL tự tải khi có snapshot_id — dùng id dòng kết quả đã lưu.
                'snapshot_id': line.id,
                'company_id': self.company_id.id,
            },
        }

    # ------------------------------------------------------------------
    # Payload M5
    # ------------------------------------------------------------------

    @api.model
    def get_m5_payload(self, period_id):
        t0 = datetime.utcnow()
        period = self.browse(period_id)
        if not period.exists():
            return {
                'error': _('Không tìm thấy kỳ tính giá thành.'),
                'elapsed_seconds': 0,
            }
        ver = period.current_result_id
        header = self._m5_header(period, ver)
        tabs = []
        if ver:
            tabs.append(self._m5_tab_summary(period, ver))
            sheet_tab = self._m5_tab_cost_sheet(period, ver)
            if sheet_tab:
                tabs.append(sheet_tab)
            alloc_tab = self._m5_tab_allocation(period)
            if alloc_tab:
                tabs.append(alloc_tab)
            direct_tab = self._m5_tab_direct(period)
            if direct_tab:
                tabs.append(direct_tab)
        elapsed = (datetime.utcnow() - t0).total_seconds()
        return {
            'error': False,
            'period_id': period.id,
            'period_name': period.name or '',
            'state': period.state,
            'state_label': dict(period._fields['state'].selection).get(
                period.state, period.state,
            ),
            'has_result': bool(ver),
            'empty_message': False if ver else _(
                'Kỳ chưa tính giá thành — chưa có phiên bản kết quả hiệu lực. '
                'Mở biểu mẫu kỳ để nhận phân bổ / tính giá thành.'
            ),
            'header': header,
            'tabs': tabs,
            'currency_id': period.currency_id.id,
            'elapsed_seconds': round(elapsed, 3),
            'elapsed_ms': int(elapsed * 1000),
        }

    @api.model
    def _m5_header(self, period, ver):
        base = {
            'date_from': fields.Date.to_string(period.date_from),
            'date_to': fields.Date.to_string(period.date_to),
        }
        if not ver:
            base.update({
                'opening_wip': False,
                'period_incurred': False,
                'cost_reduction': False,
                'closing_wip': False,
                'total_cost': False,
            })
            return base
        incurred = float_round(
            (ver.amount_direct or 0.0) + (ver.amount_overhead or 0.0), 2,
        )
        base.update({
            'opening_wip': ver.opening_wip,
            'period_incurred': incurred,
            'cost_reduction': ver.amount_reduction,
            'closing_wip': ver.closing_wip,
            'total_cost': ver.total_cost,
            'version': ver.version,
            'version_id': ver.id,
        })
        return base

    @api.model
    def _m5_tab_summary(self, period, ver):
        """Tab Tổng hợp chi phí — từng dòng = result.line đã lưu."""
        rows = []
        for line in ver.line_ids.sorted(
            lambda l: (l.cost_object_id.code or '', l.id),
        ):
            incurred = float_round(
                (line.amount_direct or 0.0) + (line.amount_overhead or 0.0), 2,
            )
            rows.append({
                'cost_object_id': line.cost_object_id.id,
                'code': line.cost_object_id.code or '',
                'name': line.cost_object_id.name or '',
                'opening_wip': line.opening_wip,
                'period_incurred': incurred,
                'cost_reduction': line.amount_reduction,
                'closing_wip': line.closing_wip,
                'total_cost': line.total_cost,
                'clickable': True,
            })
        total = float_round(sum(r['total_cost'] or 0.0 for r in rows), 2)
        return {
            'key': 'summary',
            'label': _('Tổng hợp chi phí'),
            'kind': 'summary',
            'rows': rows,
            'total': {
                'opening_wip': float_round(
                    sum(r['opening_wip'] or 0.0 for r in rows), 2,
                ),
                'period_incurred': float_round(
                    sum(r['period_incurred'] or 0.0 for r in rows), 2,
                ),
                'cost_reduction': float_round(
                    sum(r['cost_reduction'] or 0.0 for r in rows), 2,
                ),
                'closing_wip': float_round(
                    sum(r['closing_wip'] or 0.0 for r in rows), 2,
                ),
                'total_cost': total,
            },
        }

    @api.model
    def _m5_cost_item_columns(self, company):
        """Cột khoản mục động — lá đang dùng trong danh mục công ty."""
        items = self.env['vas.cost.item'].search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ], order='code, id')
        # Chỉ lá (không phải nút tổng hợp)
        leaves = items.filtered(lambda i: not i.is_aggregate_node)
        return [{
            'id': i.id,
            'code': i.code or '',
            'label': i.display_name or i.name or i.code or '',
        } for i in leaves]

    @api.model
    def _m5_tab_cost_sheet(self, period, ver):
        """Bảng tính giá thành — dòng = đối tượng đã lưu; cột KM động.

        Ô KM: gom bằng hàm engine ``_direct_lines`` + ``_received_results``
        (cùng nguồn lúc tính). Cột Tổng = ``result.line.total_cost`` đã lưu.
        """
        columns = self._m5_cost_item_columns(period.company_id)
        if not ver.line_ids:
            return False

        # Gom PS trực tiếp theo (object, cost_item) — hàm engine
        by_obj_item = defaultdict(float)
        for ml in period._direct_lines():
            if not ml.cost_object_id or not ml.cost_item_id:
                continue
            by_obj_item[(ml.cost_object_id.id, ml.cost_item_id.id)] = float_round(
                by_obj_item[(ml.cost_object_id.id, ml.cost_item_id.id)]
                + (ml.debit or 0.0) - (ml.credit or 0.0),
                2,
            )
        # Overhead đã nhận — kết quả phân bổ đã lưu gắn kỳ
        for res in period._received_results():
            item = res.run_id.cost_item_id
            obj = res.cost_object_id
            if not item or not obj:
                continue
            by_obj_item[(obj.id, item.id)] = float_round(
                by_obj_item[(obj.id, item.id)] + (res.amount or 0.0), 2,
            )

        rows = []
        for line in ver.line_ids.sorted(
            lambda l: (l.cost_object_id.code or '', l.id),
        ):
            cells = {}
            for col in columns:
                amt = by_obj_item.get((line.cost_object_id.id, col['id']), 0.0)
                cells[str(col['id'])] = amt if not float_is_zero(amt, 2) else False
            rows.append({
                'cost_object_id': line.cost_object_id.id,
                'code': line.cost_object_id.code or '',
                'name': line.cost_object_id.name or '',
                'cells': cells,
                'total_cost': line.total_cost,
                'clickable': True,
            })
        grand = float_round(sum(r['total_cost'] or 0.0 for r in rows), 2)
        return {
            'key': 'cost_sheet',
            'label': _('Bảng tính giá thành'),
            'kind': 'cost_sheet',
            'columns': columns,
            'rows': rows,
            'total': {'total_cost': grand},
            'note': _(
                'Cột khoản mục gom từ nguồn engine (_direct_lines + phân bổ đã nhận). '
                'Cột Tổng = total_cost đã lưu trên dòng kết quả. '
                'Số lượng / đơn giá thành phẩm: chưa lưu trên kết quả — không hiện.'
            ),
        }

    @api.model
    def _m5_tab_allocation(self, period):
        """Tab phân bổ chi phí chung — kết quả đã nhận (đã lưu)."""
        results = period._received_results()
        if not results:
            return False
        rows = []
        for res in results.sorted(
            lambda r: (r.run_id.name or '', r.cost_object_id.code or '', r.id),
        ):
            rows.append({
                'run': res.run_id.display_name or res.run_id.name or '',
                'cost_item': (
                    res.run_id.cost_item_id.display_name
                    or res.run_id.cost_item_id.code or ''
                ),
                'cost_object_id': res.cost_object_id.id,
                'code': res.cost_object_id.code or '',
                'name': res.cost_object_id.name or '',
                'amount': res.amount,
                'ratio_display': res.ratio_display,
                'clickable': True,
            })
        return {
            'key': 'allocation',
            'label': _('Bảng phân bổ chi phí chung'),
            'kind': 'allocation',
            'rows': rows,
            'total': {
                'amount': float_round(sum(r['amount'] or 0.0 for r in rows), 2),
            },
        }

    @api.model
    def _m5_tab_direct(self, period):
        """Tab chi phí trực tiếp — chứng từ gốc qua ``_direct_lines`` (hàm engine)."""
        lines = period._direct_lines()
        if not lines:
            return False
        rows = []
        for ml in lines.sorted(lambda l: (l.date, l.move_id.name or '', l.id)):
            rows.append({
                'date': fields.Date.to_string(ml.date) if ml.date else '',
                'move': ml.move_id.name or '',
                'account': ml.account_id.code or '',
                'cost_item': (
                    ml.cost_item_id.display_name or ml.cost_item_id.code or ''
                ),
                'cost_object_id': ml.cost_object_id.id if ml.cost_object_id else False,
                'code': ml.cost_object_id.code if ml.cost_object_id else '',
                'name': ml.cost_object_id.name if ml.cost_object_id else '',
                'debit': ml.debit,
                'credit': ml.credit,
                'clickable': bool(ml.cost_object_id),
            })
        return {
            'key': 'direct',
            'label': _('Chi phí trực tiếp'),
            'kind': 'direct',
            'rows': rows,
            'total': {
                'debit': float_round(sum(r['debit'] or 0.0 for r in rows), 2),
                'credit': float_round(sum(r['credit'] or 0.0 for r in rows), 2),
            },
        }

    @api.model
    def get_m5_totals_compare(self, period_id):
        """Đối chiếu máy: tổng đầu M5 = tổng tab tổng hợp = tổng bảng tính GT."""
        data = self.get_m5_payload(period_id)
        if data.get('error') or not data.get('has_result'):
            return {
                'ok': False,
                'header_total': False,
                'summary_total': False,
                'sheet_total': False,
            }
        header_total = data['header'].get('total_cost')
        summary = next(
            (t for t in data['tabs'] if t['key'] == 'summary'), None,
        )
        sheet = next(
            (t for t in data['tabs'] if t['key'] == 'cost_sheet'), None,
        )
        summary_total = summary['total']['total_cost'] if summary else False
        sheet_total = sheet['total']['total_cost'] if sheet else False
        ok = (
            summary_total is not False
            and sheet_total is not False
            and float_is_zero(header_total - summary_total, 2)
            and float_is_zero(header_total - sheet_total, 2)
        )
        return {
            'ok': ok,
            'header_total': header_total,
            'summary_total': summary_total,
            'sheet_total': sheet_total,
            'period_name': data.get('period_name'),
        }


class VasCostingResultLineS18Report(models.Model):
    _inherit = 'vas.costing.result.line'

    @api.model
    def get_report_data(self, options):
        """Hợp đồng khung OWL — thẻ S18 một đối tượng từ dòng kết quả đã lưu.

        ``options['snapshot_id']`` = id ``vas.costing.result.line`` (đường
        auto-load của vas_report_client, không sửa khung).
        """
        options = options or {}
        line_id = options.get('snapshot_id') or options.get('result_line_id')
        line = self.browse(line_id)
        if not line.exists():
            raise UserError(_(
                'Không tìm thấy dòng kết quả giá thành để xem thẻ S18.'
            ))
        ver = line.version_id
        period = ver.period_id
        incurred = float_round(
            (line.amount_direct or 0.0) + (line.amount_overhead or 0.0), 2,
        )
        columns = [
            {'name': 'label', 'label': _('Chỉ tiêu'), 'type': 'string', 'align': 'left'},
            {'name': 'amount', 'label': _('Số tiền'), 'type': 'monetary', 'align': 'right'},
        ]
        rows_spec = [
            (_('Dở dang đầu kỳ'), line.opening_wip),
            (_('Chi phí trực tiếp'), line.amount_direct),
            (_('Chi phí chung đã nhận'), line.amount_overhead),
            (_('Phát sinh trong kỳ'), incurred),
            (_('Khoản giảm giá thành'), line.amount_reduction),
            (_('Dở dang cuối kỳ'), line.closing_wip),
            (_('Tổng giá thành'), line.total_cost),
        ]
        lines = []
        for idx, (label, amount) in enumerate(rows_spec):
            lines.append({
                'id': 's18_%s' % idx,
                'label': label,
                'level': 0,
                'values': [label, amount],
                'unfoldable': False,
                'unfolded': False,
                'parent_id': False,
                'is_total': idx == len(rows_spec) - 1,
                'is_leaf': True,
                'class': 'o_vas_report_total' if idx == len(rows_spec) - 1 else '',
            })
        return {
            'meta': {
                'title': _('THẺ TÍNH GIÁ THÀNH S18-DNN'),
                'form_code': 'S18-DNN',
                'company_name': period.company_id.name or '',
                'period_label': _(
                    'Kỳ %(p)s · Đối tượng %(o)s · Phiên bản v%(v)s',
                    p=period.name or '',
                    o=line.cost_object_id.display_name or '',
                    v=ver.version,
                ),
                'currency_id': line.currency_id.id,
                'warning': False,
                'requires_account': False,
            },
            'columns': columns,
            'lines': lines,
            'options': {
                'snapshot_id': line.id,
                'company_id': period.company_id.id,
            },
            'checks': {},
        }

    @api.model
    def action_export_xlsx_options(self, options):
        raise UserError(_(
            'Xuất XLSX thẻ S18 từng đối tượng chưa làm trong lượt này.'
        ))

    @api.model
    def action_export_pdf_options(self, options):
        raise UserError(_(
            'Xuất PDF thẻ S18 từng đối tượng chưa làm trong lượt này.'
        ))
