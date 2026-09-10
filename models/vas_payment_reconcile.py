# -*- coding: utf-8 -*-
"""Đối soát thanh toán VietQR — treo TK 113 rồi xác nhận vào 111/112.

Phase 1: sổ VAS (không thay R17 thu tiền đã về NH). Luồng:
  HĐ + reference_code → ghi tạm Nợ 113 / Có 131 → import sao kê → match
  → Nợ 112 (hoặc 111) / Có 113.
"""
import base64
import csv
import io
import logging
import re
from datetime import timedelta
from urllib.parse import quote

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero

_logger = logging.getLogger(__name__)

REF_CODE_RE = re.compile(r'HD\d{4,12}', re.IGNORECASE)
STALE_DAYS_DEFAULT = 5
AMOUNT_TIME_WINDOW_DAYS = 2


def _normalize_ref(text):
    if not text:
        return ''
    return re.sub(r'[^A-Z0-9]', '', (text or '').upper())


class AccountMoveVietQR(models.Model):
    _inherit = 'account.move'

    vas_payment_ref_code = fields.Char(
        string='Mã CK VietQR',
        copy=False,
        index=True,
        help='Nội dung chuyển khoản chuẩn hóa (VD HD00234) — dùng đối soát sao kê.',
    )
    vas_vietqr_image = fields.Binary(
        string='VietQR',
        attachment=True,
        copy=False,
        help='Ảnh QR động (sinh từ cấu hình ngân hàng công ty + số tiền + mã CK).',
    )
    vas_vietqr_payload = fields.Char(
        string='VietQR URL',
        copy=False,
    )

    def action_vas_generate_payment_ref(self):
        for move in self.filtered(lambda m: m.is_sale_document(include_receipts=True)):
            move.vas_payment_ref_code = move._vas_build_payment_ref_code()
        return True

    def action_vas_generate_vietqr(self):
        self.action_vas_generate_payment_ref()
        for move in self:
            move._vas_refresh_vietqr_image()
        return True

    def _vas_build_payment_ref_code(self):
        self.ensure_one()
        digits = re.sub(r'\D', '', self.name or '') or str(self.id)
        # Giữ tối đa 10 chữ số cuối → HD + digits (ngắn, dễ hiện trên sao kê).
        digits = digits[-10:]
        return f'HD{digits}'

    def _vas_refresh_vietqr_image(self):
        """Sinh ảnh QR qua VietQR.io (không hard-depend thư viện EMV)."""
        self.ensure_one()
        company = self.company_id
        bin_code = (company.vas_vietqr_bank_bin or '').strip()
        acc_no = (company.vas_vietqr_account_no or '').strip()
        acc_name = (company.vas_vietqr_account_name or company.name or '').strip()
        if not bin_code or not acc_no:
            raise UserError(_(
                'Chưa cấu hình VietQR trên công ty (BIN ngân hàng + số TK). '
                'Vào Cài đặt công ty / Connecta VAS.'
            ))
        if not self.vas_payment_ref_code:
            self.vas_payment_ref_code = self._vas_build_payment_ref_code()
        amount = abs(self.amount_residual or self.amount_total or 0.0)
        # API ảnh công khai VietQR.io — template compact2.
        url = (
            f'https://img.vietqr.io/image/{quote(bin_code)}-{quote(acc_no)}-compact2.png'
            f'?amount={int(round(amount))}'
            f'&addInfo={quote(self.vas_payment_ref_code)}'
            f'&accountName={quote(acc_name)}'
        )
        self.vas_vietqr_payload = url
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=15) as resp:
                self.vas_vietqr_image = base64.b64encode(resp.read())
        except Exception as err:
            _logger.warning('VietQR image fetch failed move=%s: %s', self.id, err)
            raise UserError(_(
                'Không tải được ảnh VietQR (%(err)s). '
                'Kiểm tra BIN/số TK hoặc mạng.',
                err=err,
            )) from err


class VasPaymentPending113(models.Model):
    """Bút toán tạm Nợ 113 / Có 131 — chờ đối soát sao kê."""

    _name = 'vas.payment.pending113'
    _description = 'Thu tiền đang chuyển (TK 113)'
    _order = 'date desc, id desc'

    name = fields.Char(string='Mã', required=True, copy=False, default='New')
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id', store=True,
    )
    date = fields.Date(
        string='Ngày ghi nhận', required=True,
        default=fields.Date.context_today,
    )
    partner_id = fields.Many2one('res.partner', string='Khách hàng', required=True)
    invoice_id = fields.Many2one(
        'account.move', string='Hóa đơn',
        domain="[('move_type', 'in', ('out_invoice', 'out_receipt')), "
               "('company_id', '=', company_id), ('state', '=', 'posted')]",
        index=True,
    )
    reference_code = fields.Char(
        string='Mã CK', index=True, required=True,
        help='Khớp nội dung chuyển khoản trên sao kê (VD HD00234).',
    )
    amount = fields.Monetary(string='Số tiền', required=True, currency_field='currency_id')
    state = fields.Selection(
        [
            ('draft', 'Nháp'),
            ('pending', 'Treo 113'),
            ('matched', 'Đã đối soát'),
            ('cancelled', 'Hủy'),
        ],
        default='draft', required=True, index=True,
    )
    pending_move_id = fields.Many2one('vas.move', string='BT tạm 113/131', readonly=True)
    settle_move_id = fields.Many2one('vas.move', string='BT xác nhận 112/113', readonly=True)
    match_method = fields.Selection(
        [
            ('reference_code', 'Theo mã CK'),
            ('amount_time', 'Theo số tiền + thời gian'),
            ('manual', 'Xác nhận tay'),
        ],
        string='Cách khớp', readonly=True,
    )
    matched_line_id = fields.Many2one(
        'vas.bank.statement.line', string='Dòng sao kê', readonly=True,
    )
    matched_uid = fields.Many2one('res.users', string='Người khớp', readonly=True)
    matched_date = fields.Datetime(string='Thời điểm khớp', readonly=True)
    note = fields.Text(string='Ghi chú')
    is_stale = fields.Boolean(
        string='Treo quá hạn', compute='_compute_is_stale', search='_search_is_stale',
    )

    @api.depends('date', 'state', 'company_id.vas_payment_113_stale_days')
    def _compute_is_stale(self):
        today = fields.Date.context_today(self)
        for rec in self:
            days = rec.company_id.vas_payment_113_stale_days or STALE_DAYS_DEFAULT
            rec.is_stale = bool(
                rec.state == 'pending'
                and rec.date
                and (today - rec.date).days > days
            )

    def _search_is_stale(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return []
        today = fields.Date.context_today(self)
        pending = self.search([('state', '=', 'pending')])
        stale_ids = []
        for rec in pending:
            days = rec.company_id.vas_payment_113_stale_days or STALE_DAYS_DEFAULT
            if rec.date and (today - rec.date).days > days:
                stale_ids.append(rec.id)
        if (operator == '=' and value) or (operator == '!=' and not value):
            return [('id', 'in', stale_ids)]
        return [('id', 'not in', stale_ids)]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'vas.payment.pending113'
                ) or _('113/%s', fields.Date.context_today(self))
            if not vals.get('reference_code') and vals.get('invoice_id'):
                inv = self.env['account.move'].browse(vals['invoice_id'])
                if not inv.vas_payment_ref_code:
                    inv.action_vas_generate_payment_ref()
                vals['reference_code'] = inv.vas_payment_ref_code
            if vals.get('invoice_id') and not vals.get('partner_id'):
                inv = self.env['account.move'].browse(vals['invoice_id'])
                vals['partner_id'] = inv.partner_id.id
            if vals.get('invoice_id') and not vals.get('amount'):
                inv = self.env['account.move'].browse(vals['invoice_id'])
                vals['amount'] = abs(inv.amount_residual or inv.amount_total)
        return super().create(vals_list)

    @api.onchange('invoice_id')
    def _onchange_invoice_id(self):
        if not self.invoice_id:
            return
        inv = self.invoice_id
        self.partner_id = inv.partner_id
        self.amount = abs(inv.amount_residual or inv.amount_total)
        if not inv.vas_payment_ref_code:
            inv.action_vas_generate_payment_ref()
        self.reference_code = inv.vas_payment_ref_code

    def action_post_pending(self):
        """Ghi sổ tạm Nợ 113 / Có 131."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Chỉ ghi tạm được bản nháp.'))
            if float_is_zero(rec.amount, precision_digits=2):
                raise UserError(_('Số tiền phải > 0.'))
            if not rec.reference_code:
                raise UserError(_('Thiếu mã chuyển khoản.'))
            move = rec._create_vas_move_113_131()
            rec.write({
                'state': 'pending',
                'pending_move_id': move.id,
            })
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == 'matched':
                raise UserError(_('Đã đối soát — không hủy trực tiếp. Đảo bút toán xác nhận trước.'))
            if rec.pending_move_id and rec.pending_move_id.state == 'posted':
                rec.pending_move_id.action_reverse()
            rec.state = 'cancelled'
        return True

    def action_settle_manual(self):
        """Xác nhận tay không qua dòng sao kê (khi đã biết tiền về NH)."""
        for rec in self:
            if rec.state != 'pending':
                raise UserError(_('Chỉ xác nhận được dòng đang treo 113.'))
            settle = rec._create_vas_move_bank_113(settle_code='112')
            rec.write({
                'state': 'matched',
                'settle_move_id': settle.id,
                'match_method': 'manual',
                'matched_uid': self.env.uid,
                'matched_date': fields.Datetime.now(),
            })
        return True

    def _account(self, code):
        self.ensure_one()
        acc = self.env['vas.account'].search([
            ('code', '=', code),
            ('regime_id', '=', self.company_id.vas_regime_id.id),
        ], limit=1)
        if not acc:
            raise UserError(_('Thiếu tài khoản VAS %(code)s trên chế độ kế toán.', code=code))
        return acc

    def _payment_journal(self):
        self.ensure_one()
        journal = self.env['vas.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('code', '=', 'THU'),
        ], limit=1) or self.env['vas.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('type', 'in', ('cash', 'bank', 'general')),
        ], limit=1)
        if not journal:
            raise UserError(_('Thiếu sổ nhật ký VAS (THU) cho công ty.'))
        return journal

    def _create_vas_move_113_131(self):
        self.ensure_one()
        acc_113 = self._account('113')
        acc_131 = self._account('131')
        journal = self._payment_journal()
        amount = self.amount
        label = _('Thu đang chuyển %(ref)s', ref=self.reference_code)
        move = self.env['vas.move'].create({
            'date': self.date,
            'journal_id': journal.id,
            'regime_id': self.company_id.vas_regime_id.id,
            'move_kind': 'payment',
            'ref': label,
            'source_model': self._name,
            'source_res_id': self.id,
            'source_ref': self.display_name,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': [
                (0, 0, {
                    'account_id': acc_113.id,
                    'name': label,
                    'partner_id': self.partner_id.id,
                    'debit': amount,
                    'credit': 0.0,
                    'currency_id': self.currency_id.id,
                }),
                (0, 0, {
                    'account_id': acc_131.id,
                    'name': label,
                    'partner_id': self.partner_id.id,
                    'debit': 0.0,
                    'credit': amount,
                    'currency_id': self.currency_id.id,
                }),
            ],
        })
        move.with_context(vas_no_redirect_warning=True).action_post()
        return move

    def _create_vas_move_bank_113(self, settle_code='112'):
        self.ensure_one()
        acc_bank = self._account(settle_code)
        acc_113 = self._account('113')
        journal = self._payment_journal()
        amount = self.amount
        label = _('Xác nhận tiền về NH — %(ref)s', ref=self.reference_code)
        move = self.env['vas.move'].create({
            'date': fields.Date.context_today(self),
            'journal_id': journal.id,
            'regime_id': self.company_id.vas_regime_id.id,
            'move_kind': 'payment',
            'ref': label,
            'source_model': self._name,
            'source_res_id': self.id,
            'source_ref': self.display_name,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': [
                (0, 0, {
                    'account_id': acc_bank.id,
                    'name': label,
                    'debit': amount,
                    'credit': 0.0,
                    'currency_id': self.currency_id.id,
                }),
                (0, 0, {
                    'account_id': acc_113.id,
                    'name': label,
                    'debit': 0.0,
                    'credit': amount,
                    'currency_id': self.currency_id.id,
                }),
            ],
        })
        move.with_context(vas_no_redirect_warning=True).action_post()
        return move

    def _apply_match(self, statement_line, method, settle_code='112'):
        self.ensure_one()
        if self.state != 'pending':
            raise UserError(_('Chỉ khớp được dòng đang treo.'))
        settle = self._create_vas_move_bank_113(settle_code=settle_code)
        self.write({
            'state': 'matched',
            'settle_move_id': settle.id,
            'matched_line_id': statement_line.id,
            'match_method': method,
            'matched_uid': self.env.uid,
            'matched_date': fields.Datetime.now(),
        })
        statement_line.write({
            'state': 'matched',
            'pending_id': self.id,
            'match_method': method,
        })
        return settle


class VasBankStatementImport(models.Model):
    _name = 'vas.bank.statement.import'
    _description = 'Import sao kê ngân hàng (đối soát 113)'
    _order = 'import_date desc, id desc'

    name = fields.Char(string='Tên', required=True, default='New')
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    bank_label = fields.Char(
        string='Ngân hàng',
        help='Nhãn tự do (VD Vietcombank, MB) — Phase 1 parser generic CSV.',
    )
    import_date = fields.Datetime(
        default=fields.Datetime.now, readonly=True,
    )
    user_id = fields.Many2one(
        'res.users', default=lambda self: self.env.user, readonly=True,
    )
    data_file = fields.Binary(string='File CSV', required=True, attachment=True)
    filename = fields.Char(string='Tên file')
    settle_account_code = fields.Selection(
        [('112', '112 Tiền gửi NH'), ('111', '111 Tiền mặt')],
        string='TK nhận khi khớp',
        default='112', required=True,
    )
    state = fields.Selection(
        [('draft', 'Nháp'), ('imported', 'Đã nhập'), ('matched', 'Đã chạy khớp')],
        default='draft', required=True,
    )
    line_ids = fields.One2many(
        'vas.bank.statement.line', 'import_id', string='Dòng sao kê',
    )
    line_count = fields.Integer(compute='_compute_counts')
    matched_count = fields.Integer(compute='_compute_counts')
    unmatched_count = fields.Integer(compute='_compute_counts')

    @api.depends('line_ids', 'line_ids.state')
    def _compute_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.matched_count = len(rec.line_ids.filtered(lambda l: l.state == 'matched'))
            rec.unmatched_count = len(rec.line_ids.filtered(
                lambda l: l.state in ('unmatched', 'ambiguous')
            ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = _(
                    'SK/%(date)s',
                    date=fields.Date.context_today(self),
                )
        return super().create(vals_list)

    def action_parse_file(self):
        for rec in self:
            if not rec.data_file:
                raise UserError(_('Chưa chọn file CSV.'))
            rec.line_ids.unlink()
            rows = rec._parse_generic_csv(rec.data_file)
            Line = self.env['vas.bank.statement.line']
            for row in rows:
                Line.create({
                    'import_id': rec.id,
                    'company_id': rec.company_id.id,
                    'date': row['date'],
                    'amount': row['amount'],
                    'narration': row['narration'],
                    'balance': row.get('balance') or 0.0,
                })
            rec.state = 'imported'
        return True

    def action_run_matching(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Chưa có dòng sao kê — hãy nhập file trước.'))
            rec._run_matching_engine()
            rec.state = 'matched'
        return True

    def _parse_generic_csv(self, data_b64):
        """Parser CSV tối thiểu: date, amount, narration [, balance].

        Chấp nhận header tiếng Việt/Anh phổ biến; dấu phẩy hoặc chấm phẩy.
        """
        raw = base64.b64decode(data_b64)
        text = raw.decode('utf-8-sig', errors='replace')
        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ';' if sample.count(';') > sample.count(',') else ','
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            raise UserError(_('File CSV không có dòng tiêu đề.'))

        def _pick(row, *keys):
            lower = { (k or '').strip().lower(): v for k, v in row.items() }
            for key in keys:
                for lk, val in lower.items():
                    if key in lk and val not in (None, ''):
                        return val
            return None

        rows = []
        for row in reader:
            date_raw = _pick(row, 'date', 'ngày', 'ngay', 'transaction date', 'ngày gd')
            amount_raw = _pick(
                row, 'credit', 'có', 'amount', 'số tiền', 'so tien', 'phát sinh có',
            )
            # Một số file tách Nợ/Có — ưu tiên cột Có (tiền vào).
            if amount_raw in (None, '', '0', '0.0'):
                amount_raw = _pick(row, 'debit', 'nợ', 'no')
                if amount_raw not in (None, ''):
                    # Bỏ qua dòng chi (không phải thu) trong Phase 1.
                    continue
            narr = _pick(
                row, 'narration', 'nội dung', 'noi dung', 'description',
                'diễn giải', 'dien giai', 'remark', 'nội dung ck',
            ) or ''
            bal = _pick(row, 'balance', 'số dư', 'so du')
            if not date_raw or amount_raw in (None, ''):
                continue
            date = self._parse_date(date_raw)
            amount = self._parse_amount(amount_raw)
            if float_compare(amount, 0.0, precision_digits=2) <= 0:
                continue
            rows.append({
                'date': date,
                'amount': amount,
                'narration': narr.strip(),
                'balance': self._parse_amount(bal) if bal not in (None, '') else 0.0,
            })
        if not rows:
            raise UserError(_(
                'Không đọc được dòng thu nào. Cần cột ngày + số tiền (Có) + nội dung.'
            ))
        return rows

    @api.model
    def _parse_date(self, raw):
        raw = (raw or '').strip()
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%Y/%m/%d'):
            try:
                return fields.Date.to_date(
                    __import__('datetime').datetime.strptime(raw[:10], fmt).date()
                )
            except ValueError:
                continue
        # Excel serial? bỏ — báo lỗi rõ
        raise UserError(_('Không đọc được ngày: %s', raw))

    @api.model
    def _parse_amount(self, raw):
        if raw is None:
            return 0.0
        s = str(raw).strip().replace(' ', '').replace('\u00a0', '')
        if not s:
            return 0.0
        # 1.234.567,89 hoặc 1,234,567.89
        if s.count(',') == 1 and s.count('.') >= 1 and s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        elif s.count(',') > 1 and '.' not in s:
            s = s.replace(',', '')
        elif s.count('.') > 1 and ',' not in s:
            s = s.replace('.', '')
        elif s.count(',') == 1 and '.' not in s:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
        try:
            return abs(float(s))
        except ValueError as err:
            raise UserError(_('Không đọc được số tiền: %s', raw)) from err

    def _run_matching_engine(self):
        """Ưu tiên: (1) mã CK trong nội dung → (2) số tiền + khung ngày (đúng 1 ứng viên)."""
        self.ensure_one()
        Pending = self.env['vas.payment.pending113']
        currency = self.company_id.currency_id
        for line in self.line_ids.filtered(lambda l: l.state in ('unmatched', 'ambiguous', 'draft')):
            # --- Bước 1: reference code ---
            codes = {m.group(0).upper() for m in REF_CODE_RE.finditer(line.narration or '')}
            if codes:
                candidates = Pending.search([
                    ('company_id', '=', self.company_id.id),
                    ('state', '=', 'pending'),
                    ('reference_code', 'in', list(codes)),
                ])
                # Chuẩn hóa so khớp
                matched = candidates.filtered(
                    lambda p: _normalize_ref(p.reference_code) in {
                        _normalize_ref(c) for c in codes
                    }
                )
                if len(matched) == 1 and currency.is_zero(matched.amount - line.amount):
                    matched._apply_match(
                        line, 'reference_code',
                        settle_code=self.settle_account_code,
                    )
                    continue
                if len(matched) == 1 and not currency.is_zero(matched.amount - line.amount):
                    # Mã khớp nhưng lệch tiền → ambiguous, gợi ý
                    line.write({
                        'state': 'ambiguous',
                        'suggested_pending_ids': [(6, 0, matched.ids)],
                        'match_note': _('Mã CK khớp nhưng số tiền lệch.'),
                    })
                    continue
                if len(matched) > 1:
                    line.write({
                        'state': 'ambiguous',
                        'suggested_pending_ids': [(6, 0, matched.ids)],
                        'match_note': _('Nhiều bút toán 113 cùng mã CK.'),
                    })
                    continue

            # --- Bước 2: amount + time window, đúng 1 ứng viên ---
            date_from = line.date - timedelta(days=AMOUNT_TIME_WINDOW_DAYS)
            date_to = line.date + timedelta(days=AMOUNT_TIME_WINDOW_DAYS)
            amount_cands = Pending.search([
                ('company_id', '=', self.company_id.id),
                ('state', '=', 'pending'),
                ('date', '>=', date_from),
                ('date', '<=', date_to),
            ]).filtered(lambda p: currency.is_zero(p.amount - line.amount))
            if len(amount_cands) == 1:
                amount_cands._apply_match(
                    line, 'amount_time',
                    settle_code=self.settle_account_code,
                )
                continue
            if len(amount_cands) > 1:
                line.write({
                    'state': 'ambiguous',
                    'suggested_pending_ids': [(6, 0, amount_cands.ids)],
                    'match_note': _(
                        'Nhiều ứng viên cùng số tiền trong ±%(d)s ngày.',
                        d=AMOUNT_TIME_WINDOW_DAYS,
                    ),
                })
                continue

            # Gợi ý gần nhất (cùng số tiền bất kỳ ngày, hoặc gần tiền)
            near = Pending.search([
                ('company_id', '=', self.company_id.id),
                ('state', '=', 'pending'),
            ], order='date desc', limit=50)
            scored = []
            for p in near:
                diff = abs(p.amount - line.amount)
                day_diff = abs((p.date - line.date).days) if p.date and line.date else 99
                scored.append((diff + day_diff * 1000, p.id))
            scored.sort()
            top_ids = [pid for _, pid in scored[:5]]
            line.write({
                'state': 'unmatched',
                'suggested_pending_ids': [(6, 0, top_ids)],
                'match_note': _('Không khớp tự động.'),
            })


class VasBankStatementLine(models.Model):
    _name = 'vas.bank.statement.line'
    _description = 'Dòng sao kê ngân hàng (đối soát 113)'
    _order = 'date desc, id desc'

    import_id = fields.Many2one(
        'vas.bank.statement.import', required=True, ondelete='cascade', index=True,
    )
    company_id = fields.Many2one('res.company', required=True, index=True)
    date = fields.Date(required=True, index=True)
    amount = fields.Monetary(required=True, currency_field='currency_id')
    currency_id = fields.Many2one(related='company_id.currency_id', store=True)
    narration = fields.Char(string='Nội dung CK')
    balance = fields.Monetary(string='Số dư', currency_field='currency_id')
    state = fields.Selection(
        [
            ('draft', 'Mới'),
            ('unmatched', 'Chưa khớp'),
            ('ambiguous', 'Nghi vấn'),
            ('matched', 'Đã khớp'),
            ('ignored', 'Bỏ qua'),
        ],
        default='unmatched', required=True, index=True,
    )
    pending_id = fields.Many2one('vas.payment.pending113', string='Bút toán 113', readonly=True)
    match_method = fields.Selection(
        related='pending_id.match_method', store=True,
    )
    suggested_pending_ids = fields.Many2many(
        'vas.payment.pending113',
        'vas_bank_line_pending_rel',
        'line_id', 'pending_id',
        string='Gợi ý treo 113',
    )
    match_note = fields.Char(string='Ghi chú khớp')
    manual_pending_id = fields.Many2one(
        'vas.payment.pending113',
        string='Chọn bút toán 113',
        domain="[('company_id', '=', company_id), ('state', '=', 'pending')]",
    )

    def action_confirm_manual(self):
        for line in self:
            pending = line.manual_pending_id
            if not pending:
                raise UserError(_('Chọn bút toán 113 trước khi xác nhận.'))
            if line.state == 'matched':
                raise UserError(_('Dòng đã khớp.'))
            settle_code = line.import_id.settle_account_code or '112'
            pending._apply_match(line, 'manual', settle_code=settle_code)
        return True

    def action_ignore(self):
        self.filtered(lambda l: l.state != 'matched').write({
            'state': 'ignored',
            'match_note': _('Bỏ qua — không liên quan thu 113.'),
        })
        return True
