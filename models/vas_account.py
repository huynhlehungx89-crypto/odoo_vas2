# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools.float_utils import float_round


ENDING_BALANCE_POLICY_SELECTION = [
    ('debit', 'Dư Nợ'),
    ('credit', 'Dư Có'),
    ('debit_or_credit', 'Có thể dư Nợ hoặc dư Có'),
    ('none', 'Không có số dư cuối kỳ'),
]


class VasAccount(models.Model):
    _name = 'vas.account'
    _description = 'Tài khoản VAS'
    _order = 'code'
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_names_search = ['code', 'name']

    code = fields.Char(string='Mã', required=True, index=True, size=64)
    name = fields.Char(string='Tên', required=True)
    regime_id = fields.Many2one(
        'vas.regime',
        string='Chế độ kế toán',
        required=True,
        index=True,
        ondelete='restrict',
    )
    account_type = fields.Selection(
        selection=[
            ('asset', 'Tài sản'),
            ('liability', 'Nợ phải trả'),
            ('equity', 'Vốn chủ sở hữu'),
            ('income', 'Doanh thu'),
            ('other_income', 'Thu nhập khác'),
            ('expense', 'Chi phí'),
            ('other_expense', 'Chi phí khác'),
            ('pl', 'Xác định KQKD (911)'),
            ('off', 'Ngoài bảng'),
        ],
        string='Loại tài khoản',
        required=True,
        index=True,
    )
    ending_balance_policy = fields.Selection(
        selection=ENDING_BALANCE_POLICY_SELECTION,
        string='Tính chất số dư cuối kỳ',
        index=True,
        help='Theo cột «Tính chất số dư» Danh_Muc_TK / TT133. '
             'Tiểu khoản có cha mặc định thừa kế; TK gốc phải khai.',
    )
    parent_id = fields.Many2one(
        'vas.account',
        string='Tài khoản cha',
        index=True,
        ondelete='restrict',
    )
    parent_path = fields.Char(index=True)
    reconcile = fields.Boolean(string='Theo dõi công nợ', default=False)
    currency_id = fields.Many2one(
        'res.currency',
        string='Tiền tệ tài khoản',
        help='Forces a specific currency on this account (e.g. 1122). Empty = VND / any.',
    )
    active = fields.Boolean(string='Đang dùng', default=True)
    currency_id_balance = fields.Many2one(
        'res.currency',
        string='Tiền tệ số dư',
        compute='_compute_vas_balance',
    )
    vas_balance = fields.Monetary(
        string='Số dư sổ VAS',
        currency_field='currency_id_balance',
        compute='_compute_vas_balance',
        help='Số dư cuối kỳ hiện hành trên sổ VAS (cùng công thức F01).',
    )
    vas_balance_period_id = fields.Many2one(
        'vas.period',
        string='Kỳ số dư',
        compute='_compute_vas_balance',
    )

    _code_regime_uniq = models.Constraint(
        'UNIQUE(regime_id, code)',
        'The account code must be unique per regime.',
    )

    def _vas_smart_button_period(self, company):
        """Kỳ lịch hiện hành của công ty (cùng nghĩa bộ lọc «Kỳ hiện hành»)."""
        today = fields.Date.context_today(self)
        Period = self.env['vas.period']
        period = Period.search([
            ('fiscalyear_id.company_id', '=', company.id),
            ('date_start', '<=', today),
            ('date_end', '>=', today),
        ], limit=1)
        if period:
            return period
        return Period.search([
            ('fiscalyear_id.company_id', '=', company.id),
        ], order='date_end desc, id desc', limit=1)

    @api.depends_context('company', 'uid')
    def _compute_vas_balance(self):
        """Số dư = ``closing`` của ``_books_account_row`` (F01) — không công thức mới."""
        company = self.env.company
        period = self._vas_smart_button_period(company) if company else False
        currency = company.currency_id if company else self.env.ref('base.VND')
        Books = self.env['vas.trial.balance.wizard']
        for account in self:
            account.currency_id_balance = currency
            account.vas_balance_period_id = period
            if not company or not period:
                account.vas_balance = 0.0
                continue
            row = Books._books_account_row(
                company, account, period.date_start, period.date_end, True,
            )
            account.vas_balance = float_round(row['closing'], 2)

    def action_view_vas_move_lines(self):
        """Nút thông minh → danh sách dòng bút toán VAS của đúng TK."""
        self.ensure_one()
        period = self.vas_balance_period_id
        ctx = {
            'search_default_hide_reversed_adjustments': 1,
            'default_account_id': self.id,
        }
        if period:
            ctx['search_default_filter_current_period'] = 1
        return {
            'type': 'ir.actions.act_window',
            'name': _('Dòng bút toán — %s %s') % (self.code or '', self.name or ''),
            'res_model': 'vas.move.line',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('connecta_vas.view_vas_move_line_list').id, 'list'),
                (False, 'form'),
            ],
            'search_view_id': (
                self.env.ref('connecta_vas.view_vas_move_line_search').id, False
            ),
            'domain': [('account_id', '=', self.id)],
            'context': ctx,
            'target': 'current',
            'help': _(
                '<p class="o_view_nocontent_smiling_face">'
                'Chưa có phát sinh trên tài khoản này'
                '</p><p>Không có dòng bút toán VAS khớp bộ lọc hiện tại.</p>'
            ),
        }

    @api.onchange('parent_id')
    def _onchange_parent_id_ending_balance_policy(self):
        for account in self:
            if account.parent_id and not account.ending_balance_policy:
                account.ending_balance_policy = account.parent_id.ending_balance_policy

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._prepare_ending_balance_policy_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        if 'ending_balance_policy' in vals or 'parent_id' in vals:
            # Validate each record after merge would be messy; check intent on vals.
            if vals.get('ending_balance_policy') is False:
                vals = dict(vals)
                vals['ending_balance_policy'] = False
        res = super().write(vals)
        if 'ending_balance_policy' in vals or 'parent_id' in vals:
            for account in self:
                account._check_ending_balance_policy_required()
        return res

    def _prepare_ending_balance_policy_vals(self, vals):
        """Thừa kế từ cha; TK gốc thiếu policy → UserError tiếng Việt."""
        policy = vals.get('ending_balance_policy')
        parent_id = vals.get('parent_id')
        if not policy and parent_id:
            parent = self.browse(parent_id)
            if parent.ending_balance_policy:
                vals['ending_balance_policy'] = parent.ending_balance_policy
                policy = vals['ending_balance_policy']
        if not policy and not parent_id:
            raise UserError(
                _('Phải khai tính chất số dư cuối kỳ cho tài khoản không có tài khoản cha '
                  '(Dư Nợ / Dư Có / Có thể dư hai bên / Không có số dư cuối kỳ).')
            )
        if not policy and parent_id:
            # Cha cũng trống — vẫn chặn rõ.
            raise UserError(
                _('Tài khoản cha chưa có tính chất số dư cuối kỳ. '
                  'Khai trên tài khoản cha hoặc khai trực tiếp trên tài khoản này.')
            )

    def _check_ending_balance_policy_required(self):
        for account in self:
            if account.ending_balance_policy:
                continue
            if account.parent_id:
                if account.parent_id.ending_balance_policy:
                    # Có thể write parent_id mà quên copy — sửa im lặng? Không: bắt user.
                    raise UserError(
                        _('Tài khoản %s chưa có tính chất số dư cuối kỳ. '
                          'Nhận từ tài khoản cha hoặc khai trực tiếp.')
                        % (account.code or account.display_name,)
                    )
                raise UserError(
                    _('Tài khoản cha của %s chưa có tính chất số dư cuối kỳ. '
                      'Khai trên tài khoản cha hoặc khai trực tiếp trên tài khoản này.')
                    % (account.code or account.display_name,)
                )
            raise UserError(
                _('Phải khai tính chất số dư cuối kỳ cho tài khoản không có tài khoản cha '
                  '(Dư Nợ / Dư Có / Có thể dư hai bên / Không có số dư cuối kỳ).')
            )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        # Mirror account.account (Odoo 19): always show "{code} {name}" for VAS users.
        for account in self:
            if account.code:
                account.display_name = f"{account.code} {account.name}"
            else:
                account.display_name = account.name or ''

    def _search_display_name(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        if operator == 'in':
            names = value
            return [
                '|',
                ('code', 'in', [(name or '').split(' ')[0] for name in names]),
                ('name', 'in', names),
            ]
        if isinstance(value, str):
            name = value or ''
            return ['|', ('code', '=like', name.split(' ')[0] + '%'), ('name', operator, name)]
        return NotImplemented
