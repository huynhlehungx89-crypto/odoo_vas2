# -*- coding: utf-8 -*-
import calendar

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _


class VasFiscalyear(models.Model):
    _name = 'vas.fiscalyear'
    _description = 'Năm tài chính VAS'
    _order = 'date_from desc, id desc'

    name = fields.Char(string='Tên', required=True)
    date_from = fields.Date(
        string='Ngày bắt đầu',
        required=True,
        help='Start date, included in the fiscal year.',
    )
    date_to = fields.Date(
        string='Ngày kết thúc',
        required=True,
        help='End date, included in the fiscal year.',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Nháp'),
            ('open', 'Đang mở'),
            ('closed', 'Đã khóa'),
        ],
        string='Trạng thái',
        required=True,
        default='draft',
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )
    period_ids = fields.One2many('vas.period', 'fiscalyear_id', string='Kỳ kế toán')

    @api.model_create_multi
    def create(self, vals_list):
        """Tạo FY xong tự sinh đủ kỳ tháng (reuse action_generate_periods)."""
        fys = super().create(vals_list)
        for fy in fys:
            fy.action_generate_periods()
        return fys

    def action_generate_periods(self):
        """Generate monthly vas.period rows covering date_from..date_to.

        First/last periods may be shorter when the fiscal year does not start/end
        on month boundaries. Existing periods with the same date range are skipped.
        """
        self.ensure_one()
        Period = self.env['vas.period']
        current = self.date_from
        end = self.date_to
        created = 0
        while current <= end:
            last_day = calendar.monthrange(current.year, current.month)[1]
            month_end = current.replace(day=last_day)
            period_end = min(month_end, end)
            period_start = current
            exists = Period.search_count([
                ('fiscalyear_id', '=', self.id),
                ('date_start', '=', period_start),
                ('date_end', '=', period_end),
            ])
            if not exists:
                Period.create({
                    'name': '%02d/%d' % (period_start.month, period_start.year),
                    'date_start': period_start,
                    'date_end': period_end,
                    'fiscalyear_id': self.id,
                    'state': 'open',
                })
                created += 1
            current = period_end + relativedelta(days=1)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sinh kỳ kế toán'),
                'message': _('Đã tạo %s kỳ.', created),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_rebuild_monthly_periods(self):
        """Replace non-monthly periods with 12 monthly periods; reassign posted moves.

        Keeps vas.move rows; only clears and recomputes period_id from move.date.
        Includes orphan moves (period_id=False) whose date falls in the FY range.
        """
        self.ensure_one()
        Move = self.env['vas.move']
        moves = Move.search([
            ('company_id', '=', self.company_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        if moves:
            moves.with_context(
                vas_allow_posted_write=True,
                vas_skip_period_check=True,
            ).write({'period_id': False})
        self.period_ids.unlink()
        self.action_generate_periods()
        # Period.create already assigns orphans; safety pass for any race
        self.period_ids._assign_orphan_moves()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Tạo lại kỳ tháng'),
                'message': _(
                    'Đã tạo lại %(periods)s kỳ tháng; gán lại %(moves)s bút toán.',
                    periods=len(self.period_ids),
                    moves=len(moves),
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_assign_orphan_moves(self):
        """Gán period_id cho bút toán mồ côi thuộc các kỳ của năm này."""
        self.ensure_one()
        assigned = self.period_ids._assign_orphan_moves()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Gán bút toán mồ côi'),
                'message': _(
                    'Đã gán kỳ cho %(n)s bút toán mồ côi trong năm «%(fy)s».',
                    n=assigned,
                    fy=self.display_name,
                ),
                'type': 'success' if assigned else 'warning',
                'sticky': False,
            },
        }
