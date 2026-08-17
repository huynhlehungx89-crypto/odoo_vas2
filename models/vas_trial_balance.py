# -*- coding: utf-8 -*-
"""Bảng cân đối số phát sinh — mẫu F01-DNN (TT133).

Hợp đồng khung: get_report_data(options). Số liệu qua vas.books.mixin — không đổi công thức.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero, float_round


F01_COLUMNS = [
    {'name': 'account_code', 'label': 'Số hiệu TK', 'type': 'string', 'align': 'left'},
    {'name': 'account_name', 'label': 'Tên tài khoản', 'type': 'string', 'align': 'left'},
    {'name': 'opening_debit', 'label': 'SD đầu Nợ', 'type': 'monetary', 'align': 'right'},
    {'name': 'opening_credit', 'label': 'SD đầu Có', 'type': 'monetary', 'align': 'right'},
    {'name': 'ps_debit', 'label': 'PS Nợ', 'type': 'monetary', 'align': 'right'},
    {'name': 'ps_credit', 'label': 'PS Có', 'type': 'monetary', 'align': 'right'},
    {'name': 'closing_debit', 'label': 'SD cuối Nợ', 'type': 'monetary', 'align': 'right'},
    {'name': 'closing_credit', 'label': 'SD cuối Có', 'type': 'monetary', 'align': 'right'},
]


class VasTrialBalanceWizard(models.TransientModel):
    _name = 'vas.trial.balance.wizard'
    _inherit = ['vas.books.mixin']
    _description = 'Bảng cân đối số phát sinh VAS (F01-DNN)'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    regime_id = fields.Many2one(related='company_id.vas_regime_id', store=True)
    period_from_id = fields.Many2one(
        'vas.period', string='Từ kỳ', required=True, ondelete='cascade',
    )
    period_to_id = fields.Many2one(
        'vas.period', string='Đến kỳ', required=True, ondelete='cascade',
    )
    hide_reversed = fields.Boolean(
        string='Ẩn đã đảo/điều chỉnh',
        default=True,
        help='Tái dùng LIST_HIDE_REVERSED_DOMAIN. Tổng không đổi giữa hai chế độ.',
    )
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.ref('base.VND'), required=True,
    )
    form_code = fields.Char(default='F01-DNN', readonly=True)
    date_from = fields.Date(related='period_from_id.date_start')
    date_to = fields.Date(related='period_to_id.date_end')
    line_ids = fields.One2many(
        'vas.trial.balance.line', 'wizard_id', string='Dòng bảng', readonly=True,
    )

    total_opening_debit = fields.Monetary(currency_field='currency_id', readonly=True)
    total_opening_credit = fields.Monetary(currency_field='currency_id', readonly=True)
    total_ps_debit = fields.Monetary(currency_field='currency_id', readonly=True)
    total_ps_credit = fields.Monetary(currency_field='currency_id', readonly=True)
    total_closing_debit = fields.Monetary(currency_field='currency_id', readonly=True)
    total_closing_credit = fields.Monetary(currency_field='currency_id', readonly=True)
    diff_opening = fields.Monetary(
        string='Lệch đầu kỳ', currency_field='currency_id', readonly=True,
    )
    diff_ps = fields.Monetary(
        string='Lệch phát sinh', currency_field='currency_id', readonly=True,
    )
    diff_closing = fields.Monetary(
        string='Lệch cuối kỳ', currency_field='currency_id', readonly=True,
    )
    is_balanced = fields.Boolean(readonly=True)
    warning_text = fields.Text(string='Cảnh báo kiểm', readonly=True)

    def _check_periods(self):
        self.ensure_one()
        if not self.company_id.vas_regime_id:
            raise UserError(_('Công ty chưa chọn chế độ kế toán VAS.'))
        if self.period_from_id.date_start > self.period_to_id.date_end:
            raise UserError(_('Từ kỳ phải trước hoặc bằng Đến kỳ.'))
        for p in (self.period_from_id, self.period_to_id):
            if p.fiscalyear_id.company_id != self.company_id:
                raise UserError(_('Kỳ %(p)s không thuộc công ty đang chọn.', p=p.display_name))

    def _accounts_in_scope(self):
        """TK có dòng đến date_to — nguồn LÁ (số). Cây cha–con chỉ ở get_report_data."""
        self.ensure_one()
        domain = [
            ('move_id.company_id', '=', self.company_id.id),
            ('date', '<=', self.date_to),
            ('account_id.regime_id', '=', self.regime_id.id),
        ]
        if self.hide_reversed:
            domain += self.env['vas.move'].domain_for_amounts(prefix='move_id')
        else:
            domain.append(('move_id.state', 'in', ('posted', 'reversed')))
        lines = self.env['vas.move.line'].search(domain)
        return lines.mapped('account_id').sorted(lambda a: (a.code or '', a.id))

    def _build_warning(self, diff_opening, diff_ps, diff_closing):
        msgs = []
        if not float_is_zero(diff_opening, 2):
            msgs.append(_(
                'LỆCH Σ Đầu kỳ Nợ − Có = %(d)s',
                d='{:,.0f}'.format(diff_opening),
            ))
        if not float_is_zero(diff_ps, 2):
            msgs.append(_(
                'LỆCH Σ PS Nợ − Có = %(d)s',
                d='{:,.0f}'.format(diff_ps),
            ))
        if not float_is_zero(diff_closing, 2):
            msgs.append(_(
                'LỆCH Σ Cuối kỳ Nợ − Có = %(d)s',
                d='{:,.0f}'.format(diff_closing),
            ))
        if msgs:
            return _('CẢNH BÁO kiểm F01 — có sai sót hạch toán/tổng hợp:\n') + '\n'.join(msgs)
        return ''

    def _compute_dataset(self):
        """Lõi số F01 — dùng chung wizard form + get_report_data (không đổi công thức)."""
        self.ensure_one()
        self._check_periods()
        account_rows = []
        tot_od = tot_oc = tot_pd = tot_pc = tot_cd = tot_cc = 0.0

        for account in self._accounts_in_scope():
            row = self._books_account_row(
                self.company_id, account, self.date_from, self.date_to,
                self.hide_reversed,
            )
            if all(float_is_zero(row[k], 2) for k in (
                'opening', 'ps_debit', 'ps_credit', 'closing',
            )):
                continue
            account_rows.append({
                'account_id': account.id,
                'account_code': account.code or '',
                'account_name': account.name or '',
                'opening_debit': row['opening_debit'],
                'opening_credit': row['opening_credit'],
                'ps_debit': row['ps_debit'],
                'ps_credit': row['ps_credit'],
                'closing_debit': row['closing_debit'],
                'closing_credit': row['closing_credit'],
            })
            tot_od = float_round(tot_od + row['opening_debit'], 2)
            tot_oc = float_round(tot_oc + row['opening_credit'], 2)
            tot_pd = float_round(tot_pd + row['ps_debit'], 2)
            tot_pc = float_round(tot_pc + row['ps_credit'], 2)
            tot_cd = float_round(tot_cd + row['closing_debit'], 2)
            tot_cc = float_round(tot_cc + row['closing_credit'], 2)

        diff_opening = float_round(tot_od - tot_oc, 2)
        diff_ps = float_round(tot_pd - tot_pc, 2)
        diff_closing = float_round(tot_cd - tot_cc, 2)
        balanced = all(float_is_zero(d, 2) for d in (diff_opening, diff_ps, diff_closing))
        warning = self._build_warning(diff_opening, diff_ps, diff_closing)
        totals = {
            'opening_debit': tot_od,
            'opening_credit': tot_oc,
            'ps_debit': tot_pd,
            'ps_credit': tot_pc,
            'closing_debit': tot_cd,
            'closing_credit': tot_cc,
            'diff_opening': diff_opening,
            'diff_ps': diff_ps,
            'diff_closing': diff_closing,
            'is_balanced': balanced,
            'warning_text': warning,
        }
        return account_rows, totals

    def action_compute(self):
        self.ensure_one()
        self.line_ids.unlink()
        account_rows, totals = self._compute_dataset()
        Line = self.env['vas.trial.balance.line']
        vals_list = []
        seq = 10
        for row in account_rows:
            vals_list.append({
                'wizard_id': self.id,
                'sequence': seq,
                'row_type': 'account',
                'account_id': row['account_id'],
                'account_code': row['account_code'],
                'account_name': row['account_name'],
                'opening_debit': row['opening_debit'],
                'opening_credit': row['opening_credit'],
                'ps_debit': row['ps_debit'],
                'ps_credit': row['ps_credit'],
                'closing_debit': row['closing_debit'],
                'closing_credit': row['closing_credit'],
                'currency_id': self.currency_id.id,
            })
            seq += 10
        vals_list.append({
            'wizard_id': self.id,
            'sequence': seq,
            'row_type': 'total',
            'account_code': '',
            'account_name': _('Tổng cộng'),
            'opening_debit': totals['opening_debit'],
            'opening_credit': totals['opening_credit'],
            'ps_debit': totals['ps_debit'],
            'ps_credit': totals['ps_credit'],
            'closing_debit': totals['closing_debit'],
            'closing_credit': totals['closing_credit'],
            'currency_id': self.currency_id.id,
        })
        if vals_list:
            Line.create(vals_list)
        self.write({
            'total_opening_debit': totals['opening_debit'],
            'total_opening_credit': totals['opening_credit'],
            'total_ps_debit': totals['ps_debit'],
            'total_ps_credit': totals['ps_credit'],
            'total_closing_debit': totals['closing_debit'],
            'total_closing_credit': totals['closing_credit'],
            'diff_opening': totals['diff_opening'],
            'diff_ps': totals['diff_ps'],
            'diff_closing': totals['diff_closing'],
            'is_balanced': totals['is_balanced'],
            'warning_text': totals['warning_text'],
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def _wizard_from_options(self, options):
        options = options or {}
        company = self.env['res.company'].browse(
            options.get('company_id') or self.env.company.id
        )
        period_from = self.env['vas.period'].browse(options.get('period_from_id'))
        period_to = self.env['vas.period'].browse(options.get('period_to_id'))
        if not period_from or not period_to:
            raise UserError(_('Chọn Từ kỳ và Đến kỳ trước khi xem báo cáo.'))
        return self.create({
            'company_id': company.id,
            'period_from_id': period_from.id,
            'period_to_id': period_to.id,
            'hide_reversed': bool(options.get('hide_reversed', True)),
        })

    @api.model
    def get_report_data(self, options):
        """Hợp đồng khung OWL — F01 + cây cha–con; tổng toàn bảng chỉ từ LÁ."""
        wiz = self._wizard_from_options(options)
        account_rows, totals = wiz._compute_dataset()
        columns = [dict(c) for c in F01_COLUMNS]
        money_keys = (
            'opening_debit', 'opening_credit',
            'ps_debit', 'ps_credit',
            'closing_debit', 'closing_credit',
        )

        def make_values(row):
            return [
                row.get('account_code') or '',
                row.get('account_name') or '',
                row.get('opening_debit') or 0.0,
                row.get('opening_credit') or 0.0,
                row.get('ps_debit') or 0.0,
                row.get('ps_credit') or 0.0,
                row.get('closing_debit') or 0.0,
                row.get('closing_credit') or 0.0,
            ]

        lines = self.env['vas.report.engine'].build_account_hierarchy_lines(
            account_rows, money_keys, make_values,
        )
        # Tổng toàn báo cáo = Σ LÁ (totals từ _compute_dataset) — không cộng cha
        lines.append({
            'id': 'total',
            'label': _('Tổng cộng'),
            'level': 0,
            'values': [
                '',
                _('Tổng cộng'),
                totals['opening_debit'],
                totals['opening_credit'],
                totals['ps_debit'],
                totals['ps_credit'],
                totals['closing_debit'],
                totals['closing_credit'],
            ],
            'unfoldable': False,
            'unfolded': False,
            'parent_id': False,
            'is_total': True,
            'is_leaf': False,
            'class': 'o_vas_report_total',
        })
        return {
            'meta': {
                'title': _('BẢNG CÂN ĐỐI SỐ PHÁT SINH'),
                'form_code': 'F01-DNN',
                'company_name': wiz.company_id.name or '',
                'period_label': _('Kỳ báo cáo: từ %(a)s đến %(b)s',
                                  a=wiz.period_from_id.name, b=wiz.period_to_id.name),
                'currency_id': wiz.currency_id.id,
                'warning': totals['warning_text'] or False,
                'requires_account': False,
            },
            'columns': columns,
            'lines': lines,
            'options': {
                'company_id': wiz.company_id.id,
                'period_from_id': wiz.period_from_id.id,
                'period_to_id': wiz.period_to_id.id,
                'hide_reversed': wiz.hide_reversed,
            },
            'checks': {
                'diff_opening': totals['diff_opening'],
                'diff_ps': totals['diff_ps'],
                'diff_closing': totals['diff_closing'],
                'is_balanced': totals['is_balanced'],
            },
            'wizard_id': wiz.id,
        }

    @api.model
    def action_export_xlsx_options(self, options):
        data = self.get_report_data(options)
        # Đồng bộ line_ids cho cùng wizard (PDF/regression)
        wiz = self.browse(data['wizard_id'])
        wiz.action_compute()
        filename = 'BCDPS_F01_%s_%s.xlsx' % (
            wiz.period_from_id.name or '', wiz.period_to_id.name or '',
        )
        return self.env['vas.report.engine'].action_download_xlsx(data, filename)

    @api.model
    def action_export_pdf_options(self, options):
        data = self.get_report_data(options)
        wiz = self.browse(data['wizard_id'])
        wiz.action_compute()
        return self.env.ref('connecta_vas.action_report_vas_trial_balance').report_action(wiz)

    def action_export_xlsx(self):
        self.ensure_one()
        if not self.line_ids:
            self.action_compute()
        data = self.get_report_data({
            'company_id': self.company_id.id,
            'period_from_id': self.period_from_id.id,
            'period_to_id': self.period_to_id.id,
            'hide_reversed': self.hide_reversed,
        })
        filename = 'BCDPS_F01_%s_%s.xlsx' % (
            self.period_from_id.name or '', self.period_to_id.name or '',
        )
        return self.env['vas.report.engine'].action_download_xlsx(data, filename)

    def action_print_pdf(self):
        self.ensure_one()
        if not self.line_ids:
            self.action_compute()
        return self.env.ref('connecta_vas.action_report_vas_trial_balance').report_action(self)

    def get_report_lines(self):
        self.ensure_one()
        if not self.line_ids:
            self.action_compute()
        return self.line_ids.sorted(lambda l: (l.sequence, l.id))


class VasTrialBalanceLine(models.TransientModel):
    _name = 'vas.trial.balance.line'
    _description = 'Dòng bảng cân đối số phát sinh VAS'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'vas.trial.balance.wizard', required=True, ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    row_type = fields.Selection([
        ('account', 'Tài khoản'),
        ('total', 'Tổng cộng'),
    ], required=True, default='account')
    account_id = fields.Many2one('vas.account', string='Tài khoản')
    account_code = fields.Char(string='Số hiệu TK')
    account_name = fields.Char(string='Tên tài khoản')
    currency_id = fields.Many2one('res.currency')
    opening_debit = fields.Monetary(string='SD đầu Nợ', currency_field='currency_id')
    opening_credit = fields.Monetary(string='SD đầu Có', currency_field='currency_id')
    ps_debit = fields.Monetary(string='PS Nợ', currency_field='currency_id')
    ps_credit = fields.Monetary(string='PS Có', currency_field='currency_id')
    closing_debit = fields.Monetary(string='SD cuối Nợ', currency_field='currency_id')
    closing_credit = fields.Monetary(string='SD cuối Có', currency_field='currency_id')
