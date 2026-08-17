# -*- coding: utf-8 -*-
"""W10 — phiếu kết chuyển + sinh/ghi sổ lớp A/B.

Quyết định (thay QĐ số 6 cũ): **một lần kết chuyển = một LÔ nhiều chứng từ**,
mỗi ``vas.move`` đúng **một Nợ + một Có**. Không gộp nhiều cặp vào một chứng từ.

Lý do: chứng từ gộp không ghi lại được quan hệ đối ứng giữa các dòng — sổ chi
tiết phải đoán và đoán ra cùng một TK (911, 6422, …) đối ứng chính nó. Phụ lục 4
TT133 buộc mọi mẫu sổ có cột «tài khoản đối ứng». Đảo = đảo **trọn lô**.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round

from .vas_closing_rule import RULE_LAYER_SELECTION


class VasClosingEntry(models.Model):
    _name = 'vas.closing.entry'
    _description = 'Phiếu kết chuyển cuối kỳ'
    _order = 'date_to desc, id desc'

    name = fields.Char(
        string='Số phiếu',
        required=True,
        copy=False,
        default='/',
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )
    regime_id = fields.Many2one(
        'vas.regime',
        string='Chế độ kế toán',
        required=True,
        compute='_compute_regime_id',
        store=True,
        readonly=False,
    )
    date_to = fields.Date(
        string='Kết chuyển đến ngày',
        required=True,
        index=True,
        default=fields.Date.context_today,
    )
    date_from = fields.Date(
        string='Từ ngày',
        required=True,
        index=True,
        help='Mặc định = ngày sau lần KC posted gần nhất; chưa từng KC thì đầu năm tài chính.',
    )
    is_year_end = fields.Boolean(
        string='Cuối năm tài chính',
        compute='_compute_is_year_end',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Nháp'),
            ('ready', 'Đã lấy dữ liệu'),
            ('posted', 'Đã ghi sổ'),
            ('cancelled', 'Đã hủy'),
        ],
        default='draft',
        required=True,
        copy=False,
        index=True,
    )
    line_ids = fields.One2many(
        'vas.closing.entry.line',
        'entry_id',
        string='Dòng đề xuất',
        copy=True,
    )
    # Nhóm chạy (D2)
    run_kqkd = fields.Boolean(string='KQKD / 911', default=True)
    run_year_start = fields.Boolean(string='Đầu năm 4212→4211', default=False)
    run_fx = fields.Boolean(
        string='Chênh lệch tỷ giá (V09)',
        default=False,
        help='Đánh giá lại ngoại tệ + kết chuyển 413 → 515/635 '
             '(các chứng từ forex_reval / closing trong cùng lô).',
    )
    run_vat = fields.Boolean(
        string='Khấu trừ GTGT (L06)',
        default=False,
    )
    run_prepaid = fields.Boolean(
        string='Phân bổ 242 (C01)',
        default=False,
        help='Lấy số từ lịch vas.asset prepaid — không tự tính lại.',
    )
    run_manual = fields.Boolean(
        string='Trích/dự phòng nhập tay (C02–C07/C10)',
        default=False,
        help='Tạo dòng sẵn TK, số = 0 — kế toán điền. Cấm máy bịa số.',
    )
    run_cit = fields.Boolean(
        string='Thuế TNDN',
        default=False,
        help='Dùng cit_amount + cit_nature trên phiếu.',
    )
    # Chỗ giữ cho chặng sau (CIT) — chưa dùng
    cit_amount = fields.Monetary(
        string='Số thuế TNDN phải ghi',
        currency_field='currency_id',
        help='Số thuế do kế toán nhập (máy không tự tính từ LN).',
    )
    cit_nature = fields.Selection(
        selection=[
            ('provisional', 'Tạm nộp trong năm'),
            ('final_extra', 'Quyết toán — phải nộp thêm'),
            ('final_reduce', 'Quyết toán — được giảm / hoàn'),
            ('prior_immaterial', 'Sai sót năm trước (không trọng yếu)'),
            ('prior_material_note', 'Sai sót năm trước (trọng yếu — không qua phiếu này)'),
        ],
        string='Loại thuế TNDN',
    )
    move_ids = fields.One2many(
        'vas.move',
        'closing_entry_id',
        string='Chứng từ trong lô',
        copy=False,
        readonly=True,
        help='Mỗi dòng đề xuất → một vas.move (một Nợ / một Có). '
             'V09: move_kind=forex_reval; còn lại move_kind=closing.',
    )
    move_count = fields.Integer(
        string='Số chứng từ',
        compute='_compute_move_count',
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.ref('base.VND'),
        required=True,
    )
    warning_html = fields.Html(
        string='Cảnh báo',
        compute='_compute_warning_html',
        sanitize=False,
    )
    note = fields.Text(string='Diễn giải')
    line_count = fields.Integer(compute='_compute_line_count')
    amount_total = fields.Monetary(
        string='Tổng tiền',
        currency_field='currency_id',
        compute='_compute_amount_total',
        store=True,
    )
    accounting_date = fields.Date(
        string='Ngày hạch toán',
        help='Ngày ghi sổ bút toán kết chuyển. Mặc định = kết chuyển đến ngày.',
    )
    document_date = fields.Date(
        string='Ngày chứng từ',
        help='Ngày chứng từ trên phiếu. Mặc định = kết chuyển đến ngày.',
    )

    @api.depends('company_id', 'company_id.vas_regime_id')
    def _compute_regime_id(self):
        for rec in self:
            rec.regime_id = rec.company_id.vas_regime_id

    @api.depends('date_to', 'company_id')
    def _compute_is_year_end(self):
        FiscalYear = self.env['vas.fiscalyear']
        for rec in self:
            if not rec.date_to or not rec.company_id:
                rec.is_year_end = False
                continue
            fy = FiscalYear.search([
                ('company_id', '=', rec.company_id.id),
                ('date_to', '=', rec.date_to),
            ], limit=1)
            rec.is_year_end = bool(fy)

    @api.depends(
        'is_year_end', 'state', 'cit_nature', 'cit_amount', 'run_cit',
        'company_id', 'date_from', 'date_to', 'regime_id', 'line_ids',
    )
    def _compute_warning_html(self):
        for rec in self:
            parts = []
            if not rec.is_year_end:
                parts.append(
                    '<div class="alert alert-warning" role="alert">'
                    '<strong>Kết chuyển giữa năm.</strong> '
                    'Số liệu sau khi kết chuyển sang tài khoản xác định kết quả '
                    'và lợi nhuận năm nay là <strong>lãi (lỗ) trước thuế</strong> '
                    '— chưa kết chuyển chi phí thuế thu nhập doanh nghiệp. '
                    'Không dùng số này như lãi sau thuế cả năm.'
                    '</div>'
                )
            if (
                rec.run_cit
                and rec.cit_nature == 'prior_material_note'
                and not float_is_zero(rec.cit_amount or 0.0, precision_digits=2)
            ):
                parts.append(
                    '<div class="alert alert-danger" role="alert">'
                    '<strong>Sai sót năm trước — trọng yếu.</strong> '
                    'Theo chế độ kế toán, khoản này phải điều chỉnh hồi tố, '
                    'không hạch toán qua phiếu kết chuyển. '
                    'Xử lý riêng ngoài phiếu này. Máy không tự sinh bút toán.'
                    '</div>'
                )
            uncovered = rec._find_uncovered_pl_none_balances()
            if uncovered:
                rows = ', '.join(
                    '%s — %s (%s)' % (
                        acc.code,
                        acc.name or '',
                        '{:,.0f}'.format(amt),
                    )
                    for acc, amt, _side in uncovered[:20]
                )
                if len(uncovered) > 20:
                    rows += ', …'
                parts.append(
                    '<div class="alert alert-danger" role="alert">'
                    '<strong>Còn tài khoản kết quả chưa có quy tắc kết chuyển.</strong> '
                    'Các tài khoản sau còn số dư trong khoảng ngày nhưng không có '
                    'quy tắc đang dùng nào lấy chúng làm nguồn — máy không kết chuyển '
                    'và trước đây sẽ im lặng bỏ sót:<br/>'
                    '%s<br/><br/>'
                    'Việc cần làm: vào <em>Cấu hình → Quy tắc kết chuyển</em>, thêm '
                    '(hoặc bật) quy tắc cho từng tài khoản trên, rồi bấm Lấy dữ liệu lại.'
                    '</div>' % rows
                )
            rec.warning_html = ''.join(parts) or False

    def _covered_account_from_ids(self):
        """Tập TK nguồn được rule active phủ (đúng mã — không gộp con)."""
        self.ensure_one()
        if not self.regime_id:
            return set()
        domain = [
            ('regime_id', '=', self.regime_id.id),
            ('active', '=', True),
            ('account_from_id', '!=', False),
        ]
        if self.company_id:
            domain = [
                *domain,
                '|',
                ('company_id', '=', False),
                ('company_id', '=', self.company_id.id),
            ]
        rules = self.env['vas.closing.rule'].search(domain)
        return set(rules.mapped('account_from_id').ids)

    def _find_uncovered_pl_none_balances(self):
        """P3: P&L ``ending_balance_policy=none`` còn số dư mà không rule nào phủ.

        Trả list ``(account, amount, from_side)``. Lưới an toàn vĩnh viễn —
        bắt cả TK khách thêm trên chart mà seed không biết.
        """
        self.ensure_one()
        if not self.company_id or not self.date_from or not self.date_to or not self.regime_id:
            return []
        covered = self._covered_account_from_ids()
        Account = self.env['vas.account']
        Rule = self.env['vas.closing.rule']
        accounts = Account.search([
            ('regime_id', '=', self.regime_id.id),
            ('ending_balance_policy', '=', 'none'),
            ('account_type', 'in', (
                'income', 'other_income', 'expense', 'other_expense', 'equity', 'pl',
            )),
        ])
        open_list = []
        for acc in accounts:
            if acc.id in covered:
                continue
            amount, side = Rule.compute_closing_amount(
                acc, self.company_id, self.date_from, self.date_to, 'both',
            )
            if side:
                open_list.append((acc, amount, side))
        return open_list

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.depends('move_ids')
    def _compute_move_count(self):
        for rec in self:
            rec.move_count = len(rec.move_ids)

    def _batch_active_moves(self):
        """Chứng từ gốc của lô còn hiệu lực cộng số — dùng overlap / đảo / draft."""
        self.ensure_one()
        return self.move_ids.filtered_domain(
            self.env['vas.move'].domain_for_amounts()
        )

    @api.depends('line_ids.amount', 'line_ids.excluded')
    def _compute_amount_total(self):
        for rec in self:
            rec.amount_total = sum(
                rec.line_ids.filtered(lambda l: not l.excluded).mapped('amount')
            )

    @api.onchange('date_to')
    def _onchange_date_to_dates(self):
        if self.date_to:
            if not self.accounting_date:
                self.accounting_date = self.date_to
            if not self.document_date:
                self.document_date = self.date_to

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            date_to = vals.get('date_to')
            if date_to:
                vals.setdefault('accounting_date', date_to)
                vals.setdefault('document_date', date_to)
        records = super().create(vals_list)
        for rec, vals in zip(records, vals_list):
            if not vals.get('line_ids'):
                rec._copy_inherited_manual_lines()
        return records

    def _copy_inherited_manual_lines(self):
        """A3: phiếu mới kế thừa dòng nhập tay từ phiếu cancelled gần nhất cùng công ty/khoảng."""
        self.ensure_one()
        prev = self.search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'cancelled'),
            ('id', '!=', self.id),
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
        ], order='date_to desc, id desc', limit=1)
        if not prev:
            return
        manuals = prev.line_ids.filtered(lambda l: l.is_manual)
        if not manuals:
            return
        commands = []
        for line in manuals.sorted(lambda l: (l.sequence, l.id)):
            commands.append(fields.Command.create({
                'sequence': line.sequence,
                'name': _('(Kế thừa từ %s) %s') % (prev.name, line.name),
                'account_debit_id': line.account_debit_id.id,
                'account_credit_id': line.account_credit_id.id,
                'amount': line.amount,
                'layer': line.layer or 'B_accrual',
                'is_manual': True,
                'is_inherited': True,
                'template_code': line.template_code,
                'balance_hint': line.balance_hint,
                'excluded': line.excluded,
            }))
        if commands:
            self.write({'line_ids': commands})

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company = self.env['res.company'].browse(
            res.get('company_id') or self.env.company.id
        )
        date_to = res.get('date_to') or fields.Date.context_today(self)
        if 'date_from' in fields_list and not res.get('date_from'):
            res['date_from'] = self._suggest_date_from(company, date_to)
        if 'regime_id' in fields_list and not res.get('regime_id'):
            res['regime_id'] = company.vas_regime_id.id
        if 'accounting_date' in fields_list and not res.get('accounting_date'):
            res['accounting_date'] = date_to
        if 'document_date' in fields_list and not res.get('document_date'):
            res['document_date'] = date_to
        return res

    @api.onchange('date_to', 'company_id')
    def _onchange_date_to_suggest_from(self):
        if self.date_to and self.company_id:
            self.date_from = self._suggest_date_from(self.company_id, self.date_to)

    @api.model
    def _suggest_date_from(self, company, date_to):
        """D1: date_to lần posted gần nhất + 1; không thì đầu năm TC chứa date_to."""
        if not company or not date_to:
            return date_to
        last = self.search([
            ('company_id', '=', company.id),
            ('state', '=', 'posted'),
        ], order='date_to desc, id desc', limit=1)
        if last and last.date_to:
            return fields.Date.to_date(last.date_to) + timedelta(days=1)
        fy = self.env['vas.fiscalyear'].search([
            ('company_id', '=', company.id),
            ('date_from', '<=', date_to),
            ('date_to', '>=', date_to),
        ], limit=1)
        if fy:
            return fy.date_from
        # Fallback năm dương lịch
        d = fields.Date.to_date(date_to)
        return d.replace(month=1, day=1)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise UserError(_(
                    'Ngày «Từ ngày» (%(a)s) không được sau «Đến ngày» (%(b)s).',
                    a=rec.date_from, b=rec.date_to,
                ))

    # -------------------------------------------------------------------------
    # Lấy dữ liệu (lớp A)
    # -------------------------------------------------------------------------

    def action_fetch_data(self):
        self.ensure_one()
        if self.state not in ('draft', 'ready'):
            raise UserError(_('Chỉ lấy dữ liệu khi phiếu ở trạng thái Nháp hoặc Đã lấy dữ liệu.'))
        if not self.regime_id:
            raise UserError(_(
                'Công ty chưa chọn chế độ kế toán VAS. '
                'Vào Cài đặt → Connecta VAS để khai chế độ.'
            ))
        self._assert_writable_for_fetch()
        self._assert_no_pending_schedules()
        if not any((
            self.run_kqkd, self.run_year_start, self.run_fx,
            self.run_vat, self.run_prepaid, self.run_manual, self.run_cit,
        )):
            raise UserError(_(
                'Chọn ít nhất một nhóm để lấy dữ liệu '
                '(KQKD / đầu năm / GTGT / ngoại tệ / phân bổ 242 / nhập tay / TNDN).'
            ))

        # Giữ dòng nhập tay; xóa dòng máy sinh rồi tạo lại
        self.line_ids.filtered(lambda l: not l.is_manual).unlink()

        # Cách 1: đề xuất tuần tự — bước sau thấy bước trước qua cửa chung
        # (sổ + dòng đề xuất đã sinh), không ghi sổ từng bước.
        pending = []
        entry = self.with_context(
            vas_closing_fetch_active=True,
            vas_closing_proposal_pending=pending,
        )
        commands = []
        line_seq = 10
        for _rule_seq, _key, runner in entry._iter_fetch_units():
            cmds, line_seq = runner(line_seq)
            if cmds:
                commands.extend(cmds)
                entry._proposal_pending_extend(cmds)

        self.write({
            'line_ids': commands,
            'state': 'ready',
        })
        return True

    # -------------------------------------------------------------------------
    # Cửa chung số dư (sổ + đề xuất cùng lần bấm) + thứ tự theo rule.sequence
    # -------------------------------------------------------------------------

    def _assert_balance_door_allowed(self):
        """Chặn đọc sổ thuần khi đang lấy dữ liệu mà không qua cửa chung."""
        if (
            self.env.context.get('vas_closing_fetch_active')
            and not self.env.context.get('vas_closing_via_balance_door')
        ):
            raise UserError(_(
                'Khi lấy dữ liệu kết chuyển, mọi lần đọc số dư phải qua cửa chung '
                '(_balance_with_proposals). Không đọc sổ trực tiếp trong nhánh đề xuất.'
            ))

    def _proposal_pending_list(self):
        """List mutable trong context — cùng object xuyên suốt lần fetch."""
        pending = self.env.context.get('vas_closing_proposal_pending')
        if pending is None:
            return []
        return pending

    def _proposal_pending_extend(self, commands):
        """Ghi nhận dòng đề xuất vừa sinh để bước sau cộng vào số dư."""
        pending = self.env.context.get('vas_closing_proposal_pending')
        if pending is None:
            return
        for cmd in commands:
            vals = cmd[2] if isinstance(cmd, (tuple, list)) and len(cmd) >= 3 else cmd
            if not isinstance(vals, dict):
                continue
            debit = vals.get('account_debit_id')
            credit = vals.get('account_credit_id')
            amount = vals.get('amount') or 0.0
            if not debit or not credit or float_is_zero(amount, precision_digits=2):
                continue
            pending.append({
                'debit': debit if isinstance(debit, int) else debit.id,
                'credit': credit if isinstance(credit, int) else credit.id,
                'amount': amount,
            })

    def _ledger_signed_net(self, account, *, date_mode='period'):
        """∑Nợ − ∑Có trên sổ đã ghi (domain_for_amounts). Chỉ gọi khi đã mở cửa."""
        self._assert_balance_door_allowed()
        MoveLine = self.env['vas.move.line']
        domain = [
            ('account_id', '=', account.id),
            ('company_id', '=', self.company_id.id),
            *self.env['vas.move'].domain_for_amounts(prefix='move_id'),
        ]
        if date_mode == 'to_date':
            domain.append(('date', '<=', self.date_to))
        else:
            domain.extend([
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
            ])
        rows = MoveLine._read_group(
            domain, groupby=[], aggregates=['debit:sum', 'credit:sum'],
        )
        if not rows:
            return 0.0
        return float_round((rows[0][0] or 0.0) - (rows[0][1] or 0.0), 2)

    @api.model
    def _net_to_close_amount_side(self, net, close_side):
        """Đổi số dư thuần → (amount, from_side) giống compute_closing_amount."""
        if not close_side:
            return 0.0, False
        if close_side == 'both':
            if float_is_zero(net, precision_digits=2):
                return 0.0, False
            if float_compare(net, 0.0, precision_digits=2) > 0:
                return abs(net), 'credit'
            return abs(net), 'debit'
        if close_side == 'debit':
            if float_compare(net, 0.0, precision_digits=2) <= 0:
                return 0.0, False
            return float_round(net, precision_digits=2), 'credit'
        if close_side == 'credit':
            if float_compare(net, 0.0, precision_digits=2) >= 0:
                return 0.0, False
            return float_round(-net, precision_digits=2), 'debit'
        raise UserError(_('Bên kết chuyển không hợp lệ: %s') % close_side)

    def _balance_with_proposals(self, account, close_side, *, date_mode='period'):
        """Cửa duy nhất hỏi số dư khi sinh dòng đề xuất.

        = sổ (domain_for_amounts) + các dòng đề xuất đã sinh trước đó trong lần bấm.
        """
        self.ensure_one()
        if not account:
            return 0.0, False
        door = self.with_context(vas_closing_via_balance_door=True)
        net = door._ledger_signed_net(account, date_mode=date_mode)
        for row in self._proposal_pending_list():
            amt = row['amount']
            if row['debit'] == account.id:
                net = float_round(net + amt, 2)
            if row['credit'] == account.id:
                net = float_round(net - amt, 2)
        return self._net_to_close_amount_side(net, close_side)

    def _ending_side_amount_with_proposals(self, account, side):
        """Phần dư Nợ hoặc Có (cửa chung) — thay _ending_side_balance khi đề xuất."""
        amount, from_side = self._balance_with_proposals(account, side)
        if not from_side:
            return 0.0
        # close_side debit/credit đã trả amount cần xả phía đó
        return amount

    def _rule_by_code(self, code):
        return self.env['vas.closing.rule'].search([
            ('regime_id', '=', self.regime_id.id),
            ('code', '=', code),
        ], limit=1)

    def _iter_fetch_units(self):
        """Các đơn vị lấy dữ liệu, sắp theo ``vas.closing.rule.sequence``."""
        self.ensure_one()
        Rule = self.env['vas.closing.rule']
        units = []

        def add(seq, key, runner):
            units.append((seq, key, runner))

        if self.run_manual:
            meta = self._rule_by_code('MANUAL')
            add(meta.sequence if meta else 10, 'MANUAL', self._prepare_manual_template_commands)
        if self.run_prepaid:
            meta = self._rule_by_code('C01')
            add(meta.sequence if meta else 20, 'C01', self._prepare_c01_commands)
        if self.run_vat:
            meta = self._rule_by_code('L06')
            add(meta.sequence if meta else 30, 'L06', self._prepare_l06_commands)
        if self.run_fx:
            meta = self._rule_by_code('V09')
            add(meta.sequence if meta else 40, 'V09', self._prepare_v09_reval_commands)
            for rule in Rule.search([
                ('regime_id', '=', self.regime_id.id),
                ('active', '=', True),
                ('group_code', '=', 'fx'),
                ('timing', '=', 'after_fx_reval'),
                ('account_from_id', '!=', False),
            ], order='sequence, id'):
                add(
                    rule.sequence,
                    rule.code,
                    lambda seq, r=rule: self._run_close_rule_unit(r, seq, date_mode='to_date'),
                )
        if self.run_cit:
            meta = self._rule_by_code('CIT')
            add(meta.sequence if meta else 60, 'CIT', self._prepare_cit_commands)
        if self.run_kqkd:
            for rule in Rule.search([
                ('regime_id', '=', self.regime_id.id),
                ('active', '=', True),
                ('rule_layer', '=', 'A_close'),
                ('group_code', '=', 'kqkd'),
                ('account_from_id', '!=', False),
            ], order='sequence, id'):
                if rule.timing == 'year_end_bctc' and not self.is_year_end:
                    continue
                if rule.timing == 'after_fx_reval':
                    continue
                add(
                    rule.sequence,
                    rule.code,
                    lambda seq, r=rule: self._run_close_rule_unit(r, seq, date_mode='period'),
                )
        if self.run_year_start:
            for rule in Rule.search([
                ('regime_id', '=', self.regime_id.id),
                ('active', '=', True),
                ('rule_layer', '=', 'A_close'),
                ('group_code', '=', 'year_start'),
                ('account_from_id', '!=', False),
            ], order='sequence, id'):
                add(
                    rule.sequence,
                    rule.code,
                    lambda seq, r=rule: self._run_close_rule_unit(r, seq, date_mode='period'),
                )

        units.sort(key=lambda u: (u[0], u[1]))
        return units

    def _run_close_rule_unit(self, rule, sequence, *, date_mode='period'):
        cmds, _delta = self._commands_for_rule(rule, sequence, date_mode=date_mode)
        if not cmds:
            return [], sequence
        return cmds, sequence + 10 * len(cmds)

    def _assert_writable_for_fetch(self):
        """Chặn kỳ khóa / cutoff tại date_to — tái dùng _assert_date_writable."""
        self.env['vas.period']._assert_date_writable(
            self.company_id,
            self.date_to,
            doc_name=self.name if self.name and self.name != '/' else _('Phiếu kết chuyển'),
            allow_missing=False,
        )

    def _assert_no_pending_schedules(self):
        """Chặn lịch KH (TSCĐ) planned; prepaid planned chỉ chặn khi không chạy C01."""
        self.ensure_one()
        periods = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', self.company_id.id),
            ('date_start', '<=', self.date_to),
            ('date_end', '>=', self.date_from),
        ])
        if not periods:
            return
        # Lãi vay — luôn tái dùng gate W8
        periods._check_no_pending_loan_lines()
        # TSCĐ planned luôn chặn (A06 phải chạy pass W8 trước)
        AssetLine = self.env['vas.asset.line']
        pending_tscd = AssetLine.search([
            ('period_id', 'in', periods.ids),
            ('state', '=', 'planned'),
            ('asset_id.state', '=', 'running'),
            ('asset_id.asset_type', '=', 'tscd'),
            ('asset_id.company_id', '=', self.company_id.id),
        ])
        if pending_tscd:
            periods.filtered(
                lambda p: p.id in pending_tscd.mapped('period_id').ids
            )._check_no_pending_asset_lines()
        # Prepaid planned: nếu không chọn C01 thì chặn như gate kỳ
        if not self.run_prepaid:
            pending_pp = AssetLine.search([
                ('period_id', 'in', periods.ids),
                ('state', '=', 'planned'),
                ('asset_id.state', '=', 'running'),
                ('asset_id.asset_type', '=', 'prepaid'),
                ('asset_id.company_id', '=', self.company_id.id),
            ])
            if pending_pp:
                periods.filtered(
                    lambda p: p.id in pending_pp.mapped('period_id').ids
                )._check_no_pending_asset_lines()

    # -------------------------------------------------------------------------
    # Lớp B — L06 / V09 / C01
    # -------------------------------------------------------------------------

    def _ending_side_balance(self, account, side):
        """Số dư thuần phía Nợ/Có trên sổ — CHỈ ngoài lần lấy dữ liệu đề xuất.

        Gate / kiểm tra tay / test có thể gọi. Trong ``action_fetch_data`` phải
        dùng ``_balance_with_proposals`` / ``_ending_side_amount_with_proposals``.
        """
        self._assert_balance_door_allowed()
        MoveLine = self.env['vas.move.line']
        rows = MoveLine._read_group(
            [
                ('account_id', '=', account.id),
                ('company_id', '=', self.company_id.id),
                *self.env['vas.move'].domain_for_amounts(prefix='move_id'),
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
            ],
            groupby=[],
            aggregates=['debit:sum', 'credit:sum'],
        )
        if not rows:
            return 0.0
        debit = rows[0][0] or 0.0
        credit = rows[0][1] or 0.0
        net = float_round(debit - credit, precision_digits=2)
        if side == 'debit':
            return net if float_compare(net, 0.0, precision_digits=2) > 0 else 0.0
        return -net if float_compare(net, 0.0, precision_digits=2) < 0 else 0.0

    def _prepare_l06_commands(self, seq):
        """L06: Nợ 33311 / Có 1331|1332 = min(dư Có 33311, dư Nợ 1331+1332).

        Quy ước Connecta (TT133 không quy định thứ tự): ưu tiên xả **1331** trước,
        phần còn lại của 33311 mới sang **1332**. Kế toán soi lại trên DAC_TA.
        """
        self.ensure_one()
        Account = self.env['vas.account']
        acc_33311 = Account.search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', '33311'),
        ], limit=1)
        acc_1331 = Account.search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', '1331'),
        ], limit=1)
        acc_1332 = Account.search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', '1332'),
        ], limit=1)
        if not acc_33311 or not acc_1331:
            raise UserError(_(
                'Thiếu tài khoản 33311 hoặc 1331 trên hệ thống tài khoản TT133.'
            ))
        credit_out = self._ending_side_amount_with_proposals(acc_33311, 'credit')
        if float_is_zero(credit_out, precision_digits=2):
            return [], seq
        rule = self.env['vas.closing.rule'].search([
            ('regime_id', '=', self.regime_id.id),
            ('code', '=', 'L06'),
        ], limit=1)
        commands = []
        remain = credit_out
        for acc_in in (acc_1331, acc_1332):
            if not acc_in or float_is_zero(remain, precision_digits=2):
                continue
            debit_in = self._ending_side_amount_with_proposals(acc_in, 'debit')
            amount = float_round(min(remain, debit_in), precision_digits=2)
            if float_is_zero(amount, precision_digits=2):
                continue
            label = rule.name if rule else _('Khấu trừ GTGT đầu vào–đầu ra')
            commands.append(fields.Command.create({
                'sequence': seq,
                'rule_id': rule.id if rule else False,
                'name': _('%s (%s)') % (label, acc_in.code),
                'account_debit_id': acc_33311.id,
                'account_credit_id': acc_in.id,
                'amount': amount,
                'layer': 'B_vat',
            }))
            seq += 10
            remain = float_round(remain - amount, precision_digits=2)
        return commands, seq

    def _acc(self, code):
        return self.env['vas.account'].search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', code),
        ], limit=1)

    def _balance_hint_for(self, codes):
        """Chuỗi số dư hiện có (trong khoảng phiếu) để user so khi nhập dự phòng."""
        bits = []
        for code in codes:
            acc = self._acc(code)
            if not acc:
                continue
            if self.env.context.get('vas_closing_fetch_active'):
                debit = self._ending_side_amount_with_proposals(acc, 'debit')
                credit = self._ending_side_amount_with_proposals(acc, 'credit')
            else:
                debit = self._ending_side_balance(acc, 'debit')
                credit = self._ending_side_balance(acc, 'credit')
            if not float_is_zero(debit, precision_digits=2):
                bits.append(_('%s dư Nợ %s') % (code, '{:,.0f}'.format(debit)))
            elif not float_is_zero(credit, precision_digits=2):
                bits.append(_('%s dư Có %s') % (code, '{:,.0f}'.format(credit)))
            else:
                bits.append(_('%s = 0') % code)
        return '; '.join(bits) if bits else False

    def _prepare_manual_template_commands(self, seq):
        """C02–C07/C10 + KKTX: dòng sẵn TK, amount=0. Không đẻ trùng template đã có."""
        self.ensure_one()
        existing = set(
            self.line_ids.filtered(lambda l: l.is_manual and l.template_code)
            .mapped('template_code')
        )
        # (code, name, debit, credit, hint_codes)
        specs = [
            ('C02', _('C02 Trích trước CP phải trả'), '6422', '335', ()),
            ('C03', _('C03 Dự phòng phải thu khó đòi'), '6422', '2293', ('2293',)),
            ('C04', _('C04 Dự phòng giảm giá HTK'), '632', '2294', ('2294',)),
            ('C05', _('C05 Xóa nợ khó đòi (chọn khoản + nhập số)'), '2293', '131', ('2293',)),
            ('C06', _('C06 Dự phòng phải trả / bảo hành'), '6421', '3521', ()),
            ('C07', _('C07 Phân bổ DT chưa thực hiện'), '3387', '511', ()),
            ('C10', _('C10 Dự phòng tổn thất đầu tư'), '635', '2291', ('2291', '2292')),
            ('KKTX', _('Giá thành KKTX 154→155 (nhập tay — R15 hoãn)'), '155', '154', ()),
        ]
        commands = []
        for code, name, d_code, c_code, hints in specs:
            if code in existing:
                # Cập nhật gợi ý số dư trên dòng đã có (không đụng amount user)
                lines = self.line_ids.filtered(
                    lambda l, c=code: l.is_manual and l.template_code == c
                )
                if hints and lines:
                    lines.write({'balance_hint': self._balance_hint_for(hints)})
                continue
            debit = self._acc(d_code)
            credit = self._acc(c_code)
            if not debit or not credit:
                continue
            commands.append(fields.Command.create({
                'sequence': seq,
                'name': name,
                'account_debit_id': debit.id,
                'account_credit_id': credit.id,
                'amount': 0.0,
                'layer': 'B_accrual',
                'is_manual': True,
                'template_code': code,
                'balance_hint': self._balance_hint_for(hints) if hints else False,
            }))
            seq += 10
        return commands, seq

    def _prepare_cit_commands(self, seq):
        """V13: sinh dòng thuế TNDN từ cit_amount/cit_nature — không bịa số."""
        self.ensure_one()
        amount = self.cit_amount or 0.0
        if float_is_zero(amount, precision_digits=2):
            return [], seq
        if not self.cit_nature:
            raise UserError(_(
                'Đã bật nhóm thuế TNDN và có số thuế nhưng chưa chọn tính chất. '
                'Chọn tạm nộp / quyết toán / sai sót năm trước rồi lấy dữ liệu lại.'
            ))
        if self.cit_nature == 'prior_material_note':
            # Chỉ cảnh báo (warning_html) — không sinh dòng
            return [], seq
        acc_821 = self._acc('821')
        acc_3334 = self._acc('3334')
        if not acc_821 or not acc_3334:
            raise UserError(_('Thiếu tài khoản 821 hoặc 3334 trên hệ thống tài khoản.'))
        rule = self.env['vas.closing.rule'].search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', 'CIT'),
        ], limit=1)
        if self.cit_nature == 'final_reduce':
            debit, credit = acc_3334, acc_821
            label = _('Giảm chi phí thuế TNDN (quyết toán)')
        else:
            # provisional / final_extra / prior_immaterial → Nợ 821 / Có 3334
            debit, credit = acc_821, acc_3334
            label = _('Ghi nhận thuế TNDN')
        return [fields.Command.create({
            'sequence': seq,
            'rule_id': rule.id if rule else False,
            'name': _('%s — %s') % (label, self.cit_nature),
            'account_debit_id': debit.id,
            'account_credit_id': credit.id,
            'amount': amount,
            'layer': 'B_cit',
        })], seq + 10

    def _fx_closing_rate(self, currency):
        """Tỷ giá cuối kỳ — bắt buộc có; cấm im lặng bỏ qua (AGENT_RULES §8.1)."""
        vnd = self.env.ref('base.VND')
        if currency == vnd:
            return 1.0
        Rate = self.env['res.currency.rate']
        rate = Rate.search([
            ('currency_id', '=', currency.id),
            ('name', '<=', self.date_to),
            ('company_id', '=', self.company_id.id),
        ], order='name desc', limit=1)
        if not rate:
            rate = Rate.search([
                ('currency_id', '=', currency.id),
                ('name', '<=', self.date_to),
                ('company_id', '=', False),
            ], order='name desc', limit=1)
        if not rate:
            raise UserError(_(
                'Chưa có tỷ giá cuối kỳ cho tiền tệ %(cur)s tại ngày %(date)s '
                '(hoặc ngày trước đó).\n\n'
                'Việc cần làm: vào Kế toán → Tiền tệ, khai tỷ giá ngày '
                '%(date)s cho %(cur)s, rồi lấy dữ liệu lại.',
                cur=currency.name,
                date=self.date_to,
            ))
        # Dùng _convert để khớp chiều rate Odoo (1/VND hoặc VND-per)
        one = currency._convert(1.0, vnd, self.company_id, self.date_to)
        if float_is_zero(one, precision_digits=6):
            raise UserError(_(
                'Tỷ giá %(cur)s tại %(date)s không hợp lệ (quy đổi = 0).',
                cur=currency.name, date=self.date_to,
            ))
        return one

    def _is_monetary_fx_account(self, account):
        """V09 r264-269: 1112/1122/131/138 / 331/338/341; loại 3387 nhận trước."""
        code = account.code or ''
        if code == '3387' or code.startswith('3387'):
            return False
        return any(
            code == p or code.startswith(p)
            for p in ('1112', '1122', '131', '138', '331', '338', '341')
        )

    def _is_non_monetary_advance_balance(self, account, vnd_net):
        """Ứng trước / nhận trước (phi tiền tệ) — loại trừ khỏi V09.

        - 131* dư Có = nhận trước KH
        - 331* dư Nợ = ứng trước NCC
        """
        code = account.code or ''
        if code.startswith('131') and float_compare(vnd_net, 0.0, precision_digits=2) < 0:
            return True
        if code.startswith('331') and float_compare(vnd_net, 0.0, precision_digits=2) > 0:
            return True
        return False

    def _prepare_v09_reval_commands(self, seq):
        """Sinh dòng đánh giá lại → move forex_reval.

        Đọc vị thế NT từ sổ qua cửa (via_door). Số 413 phát sinh được bước
        ``413-515`` / ``413-635`` thấy nhờ ``_proposal_pending`` — không đắp
        ``reval_net_413`` riêng.
        """
        self.ensure_one()
        vnd = self.env.ref('base.VND')
        acc_413 = self.env['vas.account'].search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', '413'),
        ], limit=1)
        if not acc_413:
            raise UserError(_('Thiếu tài khoản 413 trên hệ thống tài khoản.'))
        rule = self.env['vas.closing.rule'].search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', 'V09'),
        ], limit=1)

        MoveLine = self.env['vas.move.line']
        door = self.with_context(vas_closing_via_balance_door=True)
        door._assert_balance_door_allowed()
        groups = MoveLine._read_group(
            [
                ('company_id', '=', self.company_id.id),
                *self.env['vas.move'].domain_for_amounts(prefix='move_id'),
                ('date', '<=', self.date_to),
                ('currency_id', '!=', False),
                ('currency_id', '!=', vnd.id),
            ],
            groupby=['account_id', 'currency_id', 'partner_id'],
            aggregates=['debit:sum', 'credit:sum', 'amount_currency:sum'],
        )
        commands = []
        for account, currency, partner, debit, credit, amt_cur in groups:
            if not account or not currency or not self._is_monetary_fx_account(account):
                continue
            vnd_net = float_round((debit or 0.0) - (credit or 0.0), 2)
            fc_net = float_round(amt_cur or 0.0, precision_digits=currency.decimal_places or 2)
            if float_is_zero(fc_net, precision_rounding=currency.rounding):
                continue
            if self._is_non_monetary_advance_balance(account, vnd_net):
                continue
            rate = self._fx_closing_rate(currency)
            target_vnd = float_round(fc_net * rate, precision_digits=2)
            delta = float_round(target_vnd - vnd_net, precision_digits=2)
            if float_is_zero(delta, precision_digits=2):
                continue
            amount = abs(delta)
            partner_name = partner.display_name if partner else ''
            label = _('Đánh giá lại %s %s %s') % (
                account.code, currency.name, partner_name,
            )
            if float_compare(delta, 0.0, precision_digits=2) > 0:
                debit_acc, credit_acc = account, acc_413
            else:
                debit_acc, credit_acc = acc_413, account
            commands.append(fields.Command.create({
                'sequence': seq,
                'rule_id': rule.id if rule else False,
                'name': label.strip(),
                'account_debit_id': debit_acc.id,
                'account_credit_id': credit_acc.id,
                'amount': amount,
                'layer': 'B_fx',
            }))
            seq += 10
        return commands, seq

    def _prepare_c01_commands(self, seq):
        """C01: lấy số từ lịch prepaid planned trong khoảng — không tự tính lại."""
        self.ensure_one()
        periods = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', self.company_id.id),
            ('date_start', '<=', self.date_to),
            ('date_end', '>=', self.date_from),
        ])
        AssetLine = self.env['vas.asset.line']
        lines = AssetLine.search([
            ('period_id', 'in', periods.ids),
            ('state', '=', 'planned'),
            ('asset_id.state', '=', 'running'),
            ('asset_id.asset_type', '=', 'prepaid'),
            ('asset_id.company_id', '=', self.company_id.id),
        ], order='period_id, id')
        if not lines:
            raise UserError(_(
                'Nhóm phân bổ 242 (C01): chưa có dòng lịch prepaid trong khoảng '
                '%(a)s → %(b)s.\n\n'
                'Việc cần làm: mở thẻ phân bổ, xác nhận để sinh lịch (pass W8), '
                'rồi lấy dữ liệu lại. Máy không tự tính số phân bổ hộ.',
                a=self.date_from, b=self.date_to,
            ))
        commands = []
        for line in lines:
            asset = line.asset_id
            expense = asset.account_expense_id
            accum = asset.account_accum_id
            if not expense or not accum:
                raise UserError(_(
                    'Thẻ %(a)s thiếu TK chi phí hoặc TK 242 — không lấy được C01.',
                    a=asset.display_name,
                ))
            if float_is_zero(line.amount, precision_digits=2):
                continue
            commands.append(fields.Command.create({
                'sequence': seq,
                'name': _('Phân bổ 242 — %s (%s)') % (
                    asset.display_name, line.period_id.display_name,
                ),
                'account_debit_id': expense.id,
                'account_credit_id': accum.id,
                'amount': line.amount,
                'layer': 'B_accrual',
                'asset_line_id': line.id,
            }))
            seq += 10
        return commands, seq

    def _prepare_layer_a_line_commands(self, start_seq=10):
        """Giữ API cũ — lớp A giờ chạy từng rule qua ``_iter_fetch_units``."""
        self.ensure_one()
        commands = []
        seq = start_seq
        for _rule_seq, key, runner in self._iter_fetch_units():
            if key in ('MANUAL', 'C01', 'L06', 'V09', 'CIT'):
                continue
            if key.startswith('413-'):
                continue
            cmds, seq = runner(seq)
            commands.extend(cmds)
        return commands

    def _commands_for_rule(self, rule, sequence, *, date_mode='period'):
        """Một rule → list Command + delta dư Nợ 911 (delta chỉ còn để tương thích)."""
        if not rule.account_from_id or not rule.close_side:
            return [], 0.0
        amount, from_side = self._balance_with_proposals(
            rule.account_from_id, rule.close_side, date_mode=date_mode,
        )
        if not from_side or float_is_zero(amount, precision_digits=2):
            return [], 0.0
        debit_acc, credit_acc = self._accounts_for_close(
            rule.account_from_id, rule.account_to_id, from_side,
        )
        cmd = fields.Command.create({
            'sequence': sequence,
            'rule_id': rule.id,
            'name': rule.name,
            'account_debit_id': debit_acc.id,
            'account_credit_id': credit_acc.id,
            'amount': amount,
            'layer': rule.rule_layer,
        })
        delta = 0.0
        if debit_acc.code == '911':
            delta += amount
        if credit_acc.code == '911':
            delta -= amount
        return [cmd], float_round(delta, 2)

    @api.model
    def _accounts_for_close(self, account_from, account_to, from_side):
        """from_side = phía ghi trên TK nguồn để xả số dư."""
        if from_side == 'debit':
            return account_from, account_to
        return account_to, account_from

    def _account_net_balance(self, account):
        """∑Nợ − ∑Có posted trong khoảng — sổ thuần (gate / ngoài fetch).

        Trong lần lấy dữ liệu đề xuất: phải dùng ``_balance_with_proposals``.
        """
        self._assert_balance_door_allowed()
        amount, side = self.env['vas.closing.rule'].compute_closing_amount(
            account, self.company_id, self.date_from, self.date_to, 'both',
        )
        if not side:
            return 0.0, None
        if side == 'debit':
            return -amount, side
        return amount, side

    def _account_net_balance_to_date(self, account):
        """∑Nợ−∑Có ≤ date_to trên sổ thuần — ngoài fetch / cửa với via_door."""
        self._assert_balance_door_allowed()
        door = self.with_context(vas_closing_via_balance_door=True)
        net = door._ledger_signed_net(account, date_mode='to_date')
        return net, None

    # -------------------------------------------------------------------------
    # Ghi sổ / đảo
    # -------------------------------------------------------------------------

    def action_post(self):
        for rec in self:
            rec._post_one()
        return True

    def _post_one(self):
        """Sinh **một chứng từ / một dòng đề xuất** (một Nợ–một Có), theo thứ tự.

        Không gộp nhiều cặp vào một ``vas.move`` — xem docstring module.
        """
        self.ensure_one()
        if self.state not in ('draft', 'ready'):
            raise UserError(_('Chỉ ghi sổ phiếu Nháp hoặc Đã lấy dữ liệu.'))
        lines = self.line_ids.filtered(
            lambda l: not l.excluded and not float_is_zero(l.amount, precision_digits=2)
        )
        if not lines:
            raise UserError(_(
                'Phiếu không có dòng kết chuyển nào để ghi sổ. '
                'Bấm «Lấy dữ liệu» hoặc thêm dòng thủ công.'
            ))
        self._assert_writable_for_fetch()
        self._assert_no_overlap_posted()

        journal = self.env['vas.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('code', '=', 'KC'),
            ('type', '=', 'closing'),
        ], limit=1)
        if not journal:
            raise UserError(_(
                'Chưa có sổ nhật ký kết chuyển (KC) cho công ty này. '
                'Kiểm tra cấu hình sổ nhật ký VAS.'
            ))

        fx_lines = lines.filtered(lambda l: l.layer == 'B_fx').sorted(
            lambda l: (l.sequence, l.id),
        )
        close_lines = (lines - fx_lines).sorted(lambda l: (l.sequence, l.id))
        if not fx_lines and not close_lines:
            raise UserError(_('Không còn dòng nào để ghi sổ.'))

        created = self.env['vas.move']
        with self.env.cr.savepoint():
            for line in fx_lines:
                move = self._create_pair_move(
                    journal, line, move_kind='forex_reval',
                )
                move.action_post()
                created |= move
            for line in close_lines:
                move = self._create_pair_move(
                    journal, line, move_kind='closing',
                )
                move.action_post()
                created |= move
                # Đánh dấu lịch C01 đã ghi — gắn đúng chứng từ cặp của dòng
                if line.asset_line_id and line.asset_line_id.state == 'planned':
                    line.asset_line_id.write({
                        'state': 'posted',
                        'move_id': move.id,
                    })

        vals = {'state': 'posted'}
        if (not self.name or self.name == '/') and created:
            vals['name'] = created.sorted('id')[:1].name
        self.write(vals)

    def _create_pair_move(self, journal, line, *, move_kind):
        """Một dòng đề xuất → một ``vas.move`` đúng một Nợ + một Có."""
        self.ensure_one()
        debit = line.account_debit_id
        credit = line.account_credit_id
        if move_kind == 'forex_reval':
            ref = line.name or _('Đánh giá lại NT %s') % self.date_to
        else:
            ref = line.name or _(
                'Kết chuyển %(debit)s sang %(credit)s',
                debit=debit.code or '',
                credit=credit.code or '',
            )
        label = line.name or ref
        return self.env['vas.move'].create({
            'date': self.accounting_date or self.date_to,
            'journal_id': journal.id,
            'regime_id': self.regime_id.id,
            'move_kind': move_kind,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'closing_entry_id': self.id,
            'source_model': 'vas.closing.entry.line',
            'source_res_id': line.id,
            'source_ref': self.name if self.name and self.name != '/' else str(self.id),
            'ref': ref,
            'narration': self.note,
            'line_ids': [
                fields.Command.create({
                    'sequence': 10,
                    'account_id': debit.id,
                    'name': label,
                    'debit': line.amount,
                    'credit': 0.0,
                }),
                fields.Command.create({
                    'sequence': 20,
                    'account_id': credit.id,
                    'name': label,
                    'debit': 0.0,
                    'credit': line.amount,
                }),
            ],
        })

    def _assert_no_overlap_posted(self):
        self.ensure_one()
        rivals = self.search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'posted'),
            ('id', '!=', self.id),
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
        ])
        rivals = rivals.filtered(lambda e: bool(e._batch_active_moves()))
        if rivals:
            old = rivals[0]
            raise UserError(_(
                'Đã có phiếu kết chuyển %(name)s (từ %(a)s đến %(b)s) '
                'đã ghi sổ và chưa đảo, giao khoảng với phiếu này '
                '(%(c)s → %(d)s).\n\n'
                'Việc cần làm: mở phiếu %(name)s, bấm «Đảo / hủy», '
                'rồi lấy dữ liệu và ghi sổ lại.',
                name=old.name,
                a=old.date_from,
                b=old.date_to,
                c=self.date_from,
                d=self.date_to,
            ))

    def action_reverse_entry(self):
        """Đảo **trọn lô** chứng từ (closing + forex_reval) trong một savepoint → cancelled."""
        for rec in self:
            if rec.state != 'posted':
                raise UserError(_('Chỉ đảo được phiếu đã ghi sổ.'))
            moves = rec._batch_active_moves()
            if not moves:
                raise UserError(_('Phiếu không có bút toán để đảo.'))
            with self.env.cr.savepoint():
                for move in moves.sorted('id'):
                    move.with_context(vas_closing_batch_reverse=True).action_reverse()
                # Hoàn lịch C01 về planned nếu đang trỏ move đã đảo
                for line in rec.line_ids.filtered('asset_line_id'):
                    al = line.asset_line_id
                    if al.move_id and al.move_id.state == 'reversed':
                        al.write({'state': 'planned', 'move_id': False})
                rec.write({'state': 'cancelled'})
        return True

    def action_set_draft(self):
        for rec in self:
            if rec.state not in ('ready', 'cancelled'):
                raise UserError(_('Chỉ đưa về nháp từ trạng thái Đã lấy dữ liệu hoặc Đã hủy.'))
            if rec.state == 'cancelled' and rec._batch_active_moves():
                raise UserError(_('Phiếu đã hủy nhưng bút toán vẫn còn — liên hệ hỗ trợ.'))
            rec.write({'state': 'draft'})
        return True


class VasClosingEntryLine(models.Model):
    _name = 'vas.closing.entry.line'
    _description = 'Dòng đề xuất kết chuyển'
    _order = 'sequence, id'

    entry_id = fields.Many2one(
        'vas.closing.entry',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    rule_id = fields.Many2one(
        'vas.closing.rule',
        string='Quy tắc',
        ondelete='set null',
    )
    asset_line_id = fields.Many2one(
        'vas.asset.line',
        string='Dòng lịch phân bổ',
        ondelete='set null',
        index=True,
        help='C01: liên kết lịch prepaid nguồn số.',
    )
    is_manual = fields.Boolean(
        string='Nhập tay',
        default=False,
        help='Dòng do kế toán nhập / mẫu C02–C10 — giữ khi Lấy dữ liệu lại; kế thừa khi đảo.',
    )
    is_inherited = fields.Boolean(
        string='Kế thừa phiếu cũ',
        default=False,
        help='Số/TK lấy từ phiếu đã đảo — user vẫn sửa được.',
    )
    template_code = fields.Char(
        string='Mã mẫu',
        index=True,
        help='C02, C03, … — tránh tạo trùng khi Lấy dữ liệu.',
    )
    balance_hint = fields.Char(
        string='Số dư tham chiếu',
        help='Số dư 229x hiện có để so khi quyết mức trích/hoàn — chỉ hiện, không tự tính.',
    )
    name = fields.Char(string='Diễn giải', required=True)
    account_debit_id = fields.Many2one(
        'vas.account',
        string='TK Nợ',
        required=True,
        ondelete='restrict',
    )
    account_credit_id = fields.Many2one(
        'vas.account',
        string='TK Có',
        required=True,
        ondelete='restrict',
    )
    amount = fields.Monetary(
        string='Số tiền',
        currency_field='currency_id',
        required=True,
        default=0.0,
    )
    layer = fields.Selection(
        selection=RULE_LAYER_SELECTION,
        string='Lớp',
    )
    excluded = fields.Boolean(
        string='Bỏ lần này',
        help='Không đưa vào bút toán khi ghi sổ; giữ trên phiếu để tham khảo.',
    )
    needs_amount = fields.Boolean(
        string='Chưa nhập số',
        compute='_compute_needs_amount',
    )
    currency_id = fields.Many2one(
        related='entry_id.currency_id',
        store=True,
    )
    company_id = fields.Many2one(
        related='entry_id.company_id',
        store=True,
        index=True,
    )

    @api.depends('is_manual', 'amount')
    def _compute_needs_amount(self):
        for line in self:
            line.needs_amount = bool(
                line.is_manual and float_is_zero(line.amount or 0.0, precision_digits=2)
            )

