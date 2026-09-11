# -*- coding: utf-8 -*-
from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class VasMove(models.Model):
    _name = 'vas.move'
    _description = 'Bút toán VAS'
    _order = 'date desc, name desc, id desc'
    _rec_names_search = ['name', 'ref', 'source_ref']

    # Filter mặc định list/search "Ẩn đã đảo/điều chỉnh".
    # Cùng nghĩa loại trừ với ``domain_for_amounts``: bỏ bản bị đảo + bản đảo.
    # Báo cáo / sổ / F01 (hide_reversed=True) và mọi chỗ cộng số gọi
    # ``domain_for_amounts`` — không copy domain tay. Đổi ``domain_for_amounts``
    # = đổi số mọi báo cáo và mọi quyết định/sinh bút toán kết chuyển.
    # Đổi hằng này = đổi filter list; phải giữ khớp nghĩa loại trừ với helper.
    LIST_HIDE_REVERSED_DOMAIN = [
        ('state', '!=', 'reversed'),
        ('is_reversal', '=', False),
    ]
    # Sau post: MẶC ĐỊNH CẤM mọi field. Chỉ các field kỹ thuật dưới đây được
    # ghi không cần vas_allow_posted_write (compute/cờ hủy/gán kỳ).
    POSTED_WRITE_ALLOW = frozenset({
        'period_id',
        'period_missing_pending',
        'source_cancel_pending',
        'reversal_move_id',
    })

    @api.model
    def domain_for_amounts(self, prefix=''):
        """Điều kiện cộng số: đã ghi sổ VÀ không phải bản đảo VÀ không phải bản bị đảo.

        ``state='posted'`` đã loại bản bị đảo (``reversed``). Thêm
        ``is_reversal=False`` để loại bút toán đảo còn posted — nếu thiếu,
        đảo phiếu kết chuyển rồi lấy dữ liệu lại sẽ cộng gấp đôi.

        Dùng cho MỌI chỗ cộng số (engine kết chuyển, lưới an toàn, gate đóng kỳ,
        L06/V09, báo cáo/sổ khi ẩn đảo, …) — không riêng báo cáo. Không viết
        domain tương đương ở chỗ khác; gọi helper này.

        :param prefix: ``''`` trên ``vas.move``; ``'move_id'`` trên ``vas.move.line``.
        """
        p = ('%s.' % prefix) if prefix else ''
        return [
            ('%sstate' % p, '=', 'posted'),
            ('%sis_reversal' % p, '=', False),
        ]

    name = fields.Char(
        string='Số chứng từ',
        required=True,
        copy=False,
        default='/',
        index=True,
    )
    date = fields.Date(
        string='Ngày hạch toán',
        required=True,
        index=True,
        default=fields.Date.context_today,
    )
    period_id = fields.Many2one(
        'vas.period',
        string='Kỳ kế toán',
        compute='_compute_period_id',
        store=True,
        index=True,
        readonly=False,
    )
    journal_id = fields.Many2one(
        'vas.journal',
        string='Sổ nhật ký',
        required=True,
        index=True,
        ondelete='restrict',
    )
    regime_id = fields.Many2one(
        'vas.regime',
        string='Chế độ kế toán',
        required=True,
        index=True,
        ondelete='restrict',
        default=lambda self: self.env.company.vas_regime_id,
    )
    move_kind = fields.Selection(
        selection=[
            ('opening', 'Mở sổ'),
            ('sale_inv', 'Hóa đơn bán'),
            ('purchase_inv', 'Hóa đơn mua'),
            ('stock', 'Kho'),
            ('cogs', 'Giá vốn'),
            ('revenue', 'Doanh thu (lúc giao)'),
            ('payment', 'Thanh toán'),
            ('payment_settle', 'Xác nhận tiền về (113→112)'),
            ('refund', 'Hoàn trả'),
            ('expense', 'Chi phí'),
            ('payroll', 'Lương'),
            ('payroll_pay', 'Trả lương'),
            ('payroll_remit', 'Nộp BH/TNCN lương'),
            ('depreciation', 'Khấu hao TSCĐ'),
            ('prepaid_alloc', 'Phân bổ 242'),
            ('ccdc_issue', 'Xuất CCDC'),
            ('debt_offset', 'Bù trừ công nợ'),
            ('loan_receipt', 'Nhận tiền vay'),
            ('loan_disburse', 'Giải ngân vay trả NCC'),
            ('loan_repay', 'Trả gốc vay'),
            ('loan_interest', 'Trích lãi vay'),
            ('loan_interest_pay', 'Trả lãi vay'),
            ('capital_receipt', 'Nhận vốn góp'),
            ('profit_distribution', 'Phân phối LN / trích quỹ'),
            ('dividend_pay', 'Chi cổ tức / LN'),
            ('dividend_tax_pay', 'Nộp TNCN cổ tức'),
            ('closing', 'Kết chuyển'),
            ('manual', 'Thủ công'),
            ('landed', 'Vốn hóa cước (landed)'),
            ('landed_tax', 'Thuế hóa đơn cước'),
            ('import_vat', 'GTGT hàng NK (tờ khai)'),
            ('import_vat_payment', 'Nộp GTGT hàng NK'),
            ('goods_in_transit', 'Hàng mua đang đi đường'),
            ('forex', 'Chênh lệch tỷ giá (realized)'),
            ('forex_reval', 'Đánh giá lại ngoại tệ cuối kỳ (V09)'),
            ('pos_sale', 'Bán tại quầy'),
            ('pos_cogs', 'Giá vốn quầy'),
            ('pos_refund', 'Trả hàng tại quầy'),
            ('pos_session_cash', 'Kết ca tiền mặt quầy'),
            ('pos_session_bank', 'Kết ca thẻ/ví quầy'),
            ('pos_cash_diff', 'Lệch đếm két quầy'),
            ('pos_cash_io', 'Rút/bỏ tiền giữa ca quầy'),
            ('pos_rounding', 'Làm tròn tiền quầy'),
            ('scrap', 'Hủy hàng'),
            ('inventory_provision', 'Dự phòng giảm giá HTK'),
        ],
        string='Loại bút toán',
        required=True,
        default='manual',
        index=True,
    )
    ref = fields.Char(string='Diễn giải', index='trigram')
    source_model = fields.Char(string='Model nguồn', index=True)
    source_res_id = fields.Integer(string='ID bản ghi nguồn', index=True)
    source_ref = fields.Char(string='Tham chiếu nguồn')
    origin_ref = fields.Char(
        string='Chứng từ gốc',
        compute='_compute_origin_ref',
        store=True,
        index=True,
        help='Số đơn gốc (sale.order / purchase.order), vd S00014.',
    )
    # Gom nhóm list (khấu hao / ghi lãi) — suy từ source, không đổi engine.
    vas_asset_id = fields.Many2one(
        'vas.asset',
        string='Tài sản',
        compute='_compute_vas_source_links',
        store=True,
        index=True,
    )
    vas_loan_id = fields.Many2one(
        'vas.loan',
        string='Khế ước vay',
        compute='_compute_vas_source_links',
        store=True,
        index=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Nháp'),
            ('posted', 'Đã ghi sổ'),
            ('reversed', 'Đã đảo'),
            ('cancelled', 'Đã hủy'),
        ],
        string='Trạng thái',
        required=True,
        default='draft',
        copy=False,
        index=True,
    )
    reversal_move_id = fields.Many2one(
        'vas.move',
        string='Bút toán đảo',
        copy=False,
        index=True,
        ondelete='set null',
    )
    is_reversal = fields.Boolean(string='Là bút toán đảo', default=False, copy=False, index=True)
    source_cancel_pending = fields.Boolean(
        string='Nguồn đã hủy (kỳ đã khóa)',
        default=False,
        copy=False,
        index=True,
        help='Nguồn Odoo/VAS đã chết nhưng kỳ của bút toán đã khóa sổ — '
             'không đảo tự động; kế toán đảo tay sang kỳ mở.',
    )
    period_missing_pending = fields.Boolean(
        string='Chưa ghi sổ — thiếu kỳ',
        default=False,
        copy=False,
        index=True,
        help='Nháp lưu khi chưa có kỳ kế toán phủ ngày — không ghi sổ được '
             'cho đến khi tạo năm/kỳ rồi post lại.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Tiền tệ',
        required=True,
        default=lambda self: self.env.ref('base.VND'),
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )
    closing_entry_id = fields.Many2one(
        'vas.closing.entry',
        string='Phiếu kết chuyển',
        index=True,
        copy=False,
        ondelete='set null',
        help='Thuộc lô kết chuyển: mỗi chứng từ đúng một cặp Nợ–Có; '
             'đảo phải đảo cả lô qua phiếu (không đảo lẻ).',
    )
    vas_has_default_account = fields.Boolean(
        string='Dùng TK mặc định',
        default=False,
        index=True,
        copy=False,
        help='Bút toán có ít nhất một dòng phải rơi về tài khoản mặc định: '
             '156/5111/632 (sản phẩm/nhóm chưa khai ánh xạ), 6422 (bộ phận '
             'lương / thẻ tài sản chưa khai TK chi phí), 2141 (thẻ từ góp vốn), '
             '335/635 (thẻ vay chưa khai TK lãi), 3411 (thẻ vay chưa khai TK vay), '
             '2111 (góp vốn hiện vật chưa khai TK tài sản). '
             'Xem chi tiết ở Ghi chú. Kỳ còn bút toán loại này thì không khóa được.',
    )
    vas_has_unclassified_cost = fields.Boolean(
        string='Khoản mục chưa phân loại',
        default=False,
        index=True,
        copy=False,
        help='W12: ít nhất một dòng chi phí rơi về khoản mục hệ thống CPD '
             '«Chưa phân loại». Cùng khuôn cờ TK mặc định: lọc được, chặn khóa kỳ.',
    )
    vas_missing_cost_object = fields.Boolean(
        string='Thiếu đối tượng tập hợp',
        default=False,
        index=True,
        copy=False,
        help='R14 xuất NVL sản xuất: không suy ra được đối tượng thành phẩm '
             '(chưa khai đối tượng SP / trùng nguồn / thiếu MO). '
             'JE vẫn ghi NVLTT; cần gắn tay hoặc bổ sung danh mục trước khi tính GT.',
    )
    narration = fields.Text(string='Ghi chú')
    line_ids = fields.One2many('vas.move.line', 'move_id', string='Dòng bút toán', copy=True)

    def _refresh_missing_cost_object_flag(self, note=None):
        """Cập nhật cờ thiếu đối tượng sau gắn tay / backfill.

        Còn dòng Nợ NVLTT không đối tượng → giữ cờ; hết → tắt cờ.
        ``note`` (nếu có) nối vào narration (audit gắn tay).
        """
        for move in self:
            still_missing = bool(move.line_ids.filtered(
                lambda l: l.debit
                and l.cost_item_id
                and l.cost_item_id.code == 'NVLTT'
                and not l.cost_object_id
            ))
            vals = {'vas_missing_cost_object': still_missing}
            if note:
                narration = move.narration or ''
                if note not in narration:
                    narration = (
                        (narration + '\n' + note).strip() if narration else note
                    )
                    vals['narration'] = narration
            move.with_context(vas_allow_posted_write=True).write(vals)

    # -------------------------------------------------------------------------
    # Compute / onchange
    # -------------------------------------------------------------------------

    @api.depends('date', 'company_id')
    def _compute_period_id(self):
        Period = self.env['vas.period']
        for move in self:
            if not move.date:
                move.period_id = False
                continue
            domain = [
                ('date_start', '<=', move.date),
                ('date_end', '>=', move.date),
            ]
            if move.company_id:
                domain.append(('fiscalyear_id.company_id', '=', move.company_id.id))
            move.period_id = Period.search(domain, limit=1)

    @api.depends('source_model', 'source_res_id')
    def _compute_origin_ref(self):
        for move in self:
            move.origin_ref = move._resolve_origin_ref()

    @api.depends('source_model', 'source_res_id')
    def _compute_vas_source_links(self):
        AssetLine = self.env['vas.asset.line']
        LoanLine = self.env['vas.loan.line']
        for move in self:
            asset = self.env['vas.asset']
            loan = self.env['vas.loan']
            if move.source_model == 'vas.asset.line' and move.source_res_id:
                line = AssetLine.browse(move.source_res_id).exists()
                asset = line.asset_id
            elif move.source_model == 'vas.asset' and move.source_res_id:
                asset = self.env['vas.asset'].browse(move.source_res_id).exists()
            if move.source_model == 'vas.loan.line' and move.source_res_id:
                line = LoanLine.browse(move.source_res_id).exists()
                loan = line.loan_id
            elif move.source_model == 'vas.loan' and move.source_res_id:
                loan = self.env['vas.loan'].browse(move.source_res_id).exists()
            move.vas_asset_id = asset
            move.vas_loan_id = loan

    def _resolve_origin_ref(self):
        """Resolve original SO/PO name from Odoo source; empty if unknown."""
        self.ensure_one()
        if not self.source_model or not self.source_res_id:
            return False
        if self.source_model not in self.env:
            return False
        record = self.env[self.source_model].browse(self.source_res_id).exists()
        if not record:
            return False

        def _join_names(records):
            names = [n for n in records.mapped('name') if n]
            return ','.join(names) if names else False

        if self.source_model == 'stock.move':
            if 'sale_line_id' in record._fields and record.sale_line_id:
                return record.sale_line_id.order_id.name or False
            if 'purchase_line_id' in record._fields and record.purchase_line_id:
                return record.purchase_line_id.order_id.name or False
            if record.origin:
                return record.origin.split(',')[0].strip() or False
            return False

        if self.source_model == 'account.move':
            # sale.order via invoice lines
            if 'sale_line_ids' in record.line_ids._fields:
                orders = record.line_ids.sale_line_ids.order_id
                if orders:
                    return _join_names(orders)
            # purchase.order via bill lines
            if 'purchase_line_id' in record.invoice_line_ids._fields:
                orders = record.invoice_line_ids.mapped('purchase_line_id.order_id')
                if orders:
                    return _join_names(orders)
            if record.invoice_origin:
                return record.invoice_origin.split(',')[0].strip() or False
            return False

        if self.source_model == 'account.payment':
            invoices = self.env['account.move']
            if 'reconciled_invoice_ids' in record._fields:
                invoices |= record.reconciled_invoice_ids
            if 'invoice_ids' in record._fields:
                invoices |= record.invoice_ids
            if invoices and 'sale_line_ids' in invoices.line_ids._fields:
                orders = invoices.line_ids.sale_line_ids.order_id
                if orders:
                    return _join_names(orders)
            origins = [o.split(',')[0].strip() for o in invoices.mapped('invoice_origin') if o]
            return ','.join(origins) if origins else False

        return False

    @api.onchange('journal_id')
    def _onchange_journal_id(self):
        if self.journal_id:
            self.regime_id = self.journal_id.regime_id
            self.company_id = self.journal_id.company_id

    # -------------------------------------------------------------------------
    # Constraints (DAC §7)
    # -------------------------------------------------------------------------

    @api.constrains('source_model', 'source_res_id', 'move_kind', 'state', 'is_reversal')
    def _check_source_unique(self):
        """Idempotency: unique (source_model, source_res_id, move_kind) among non-reversed moves.

        Manual entries (empty source) are skipped. Uses @api.constrains, not SQL UNIQUE.
        """
        for move in self:
            if not move.source_model or not move.source_res_id:
                continue
            if move.is_reversal or move.state in ('reversed', 'cancelled'):
                continue
            domain = [
                ('id', '!=', move.id),
                ('source_model', '=', move.source_model),
                ('source_res_id', '=', move.source_res_id),
                ('move_kind', '=', move.move_kind),
                ('is_reversal', '=', False),
                ('state', 'not in', ('reversed', 'cancelled')),
            ]
            if self.search_count(domain):
                raise ValidationError(_(
                    "A VAS move already exists for source %(model)s(%(res_id)s) with kind %(kind)s.",
                    model=move.source_model,
                    res_id=move.source_res_id,
                    kind=move.move_kind,
                ))

    def _check_period_open(self):
        """Chặn closed trên create/write/unlink; missing vẫn cho nháp (§8.4)."""
        Period = self.env['vas.period']
        for move in self:
            Period._assert_date_writable(
                move.company_id,
                move.date,
                doc_name=move.name,
                allow_missing=True,
            )

    def _sync_period_missing_pending(self):
        """Cờ nháp thiếu kỳ — clear khi đã có kỳ phủ hoặc đã post."""
        Period = self.env['vas.period']
        for move in self:
            if move.state != 'draft':
                want = False
            else:
                want = Period._coverage_status(move.company_id, move.date) == 'missing'
            if bool(move.period_missing_pending) != want:
                move.with_context(
                    vas_skip_period_check=True,
                    vas_allow_posted_write=True,
                ).write({'period_missing_pending': want})

    # -------------------------------------------------------------------------
    # CRUD protections
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        Journal = self.env['vas.journal']
        for vals in vals_list:
            company = self.env['res.company'].browse(
                vals.get('company_id') or self.env.company.id
            )
            if vals.get('journal_id') and not vals.get('regime_id'):
                journal = Journal.browse(vals['journal_id'])
                vals['regime_id'] = journal.regime_id.id
                vals.setdefault('company_id', journal.company_id.id)
            if not vals.get('regime_id') and company.vas_regime_id:
                vals['regime_id'] = company.vas_regime_id.id
            vals.setdefault('company_id', company.id)
        moves = super().create(vals_list)
        if not self.env.context.get('vas_skip_period_check'):
            moves._check_period_open()
            moves._sync_period_missing_pending()
        return moves

    def write(self, vals):
        for move in self:
            if move.state == 'posted' and not self.env.context.get('vas_allow_posted_write'):
                forbidden = set(vals) - self.POSTED_WRITE_ALLOW
                if forbidden:
                    raise UserError(_(
                        "Posted move %(name)s is immutable. Use Reverse Entry instead. "
                        "Cannot modify: %(fields)s",
                        name=move.name,
                        fields=', '.join(sorted(forbidden)),
                    ))
            if move.state == 'posted' and 'state' in vals and vals['state'] not in ('posted', 'reversed', 'cancelled'):
                if not self.env.context.get('vas_allow_posted_write'):
                    raise UserError(_("You cannot reset a posted VAS move to draft."))
        # Closed period: block edits that keep/move the entry into a closed period
        if not self.env.context.get('vas_skip_period_check'):
            self._check_period_open()
        res = super().write(vals)
        if not self.env.context.get('vas_skip_period_check'):
            # Re-check after write (date/period may have changed)
            to_check = self.filtered(lambda m: m.state in ('draft', 'posted'))
            to_check._check_period_open()
            if 'period_missing_pending' not in vals:
                self._sync_period_missing_pending()
        return res

    def unlink(self):
        if any(move.state == 'posted' for move in self):
            raise UserError(_("You cannot delete a posted VAS move. Reverse it instead."))
        self._check_period_open()
        return super().unlink()

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def _get_accounting_currency(self):
        return self.env.ref('base.VND')

    def _check_balanced(self):
        currency = self._get_accounting_currency()
        for move in self:
            debit = sum(move.line_ids.mapped('debit'))
            credit = sum(move.line_ids.mapped('credit'))
            if float_compare(debit, credit, precision_rounding=currency.rounding) != 0:
                raise UserError(_(
                    "The entry is not balanced: debit %(debit)s ≠ credit %(credit)s.",
                    debit=debit,
                    credit=credit,
                ))

    def action_post(self):
        Period = self.env['vas.period']
        for move in self:
            if move.state != 'draft':
                raise UserError(_("Only draft moves can be posted."))
            if not move.line_ids:
                raise UserError(_("You cannot post an entry without journal items."))
            Period._assert_date_writable(
                move.company_id,
                move.date,
                doc_name=move.name,
                allow_missing=False,
                move=move,
            )
            move._check_balanced()
            vals = {'state': 'posted', 'period_missing_pending': False}
            if not move.name or move.name == '/':
                sequence = move.journal_id.sequence_id
                if not sequence:
                    raise UserError(_(
                        "Journal %(journal)s has no sequence. Configure sequence_id before posting.",
                        journal=move.journal_id.display_name,
                    ))
                vals['name'] = sequence.next_by_id()
            move.with_context(vas_allow_posted_write=True, vas_skip_period_check=True).write(vals)
            move.line_ids._vas_init_residuals()
        return True

    def _reverse_date_for_cancel(self):
        """Ngày bút toán đảo (QĐ1 / Q9).

        Coverage theo NGÀY (không tin period_id stored):
        open → giữ date gốc; closed/missing → ngày trong kỳ mở hiện hành.
        """
        self.ensure_one()
        Period = self.env['vas.period']
        status = Period._coverage_status(self.company_id, self.date)
        if status == 'open':
            return self.date

        today = fields.Date.context_today(self)
        open_period = Period.search([
            ('fiscalyear_id.company_id', '=', self.company_id.id),
            ('state', '=', 'open'),
            ('date_start', '<=', today),
            ('date_end', '>=', today),
        ], limit=1)
        if not open_period:
            open_period = Period.search([
                ('fiscalyear_id.company_id', '=', self.company_id.id),
                ('state', '=', 'open'),
            ], order='date_start desc', limit=1)
        if not open_period:
            raise UserError(_(
                "Không đảo được bút toán %(move)s: kỳ gốc đã khóa / thiếu kỳ và "
                "không còn kỳ kế toán đang mở. Mở một kỳ rồi đảo tay.",
                move=self.display_name,
            ))
        if open_period.date_start <= today <= open_period.date_end:
            return today
        return open_period.date_start

    def action_reverse(self, reverse_date=None):
        """Create and post a reversing entry; mark original as reversed (DAC §7.3).

        ``reverse_date``: nếu None → ``_reverse_date_for_cancel()`` (QĐ1).

        Savepoint bao create + gắn ``reversal_move_id`` + post đảo + đánh dấu
        gốc ``reversed`` — nếu ``action_post`` nổ (cutoff, kỳ khóa…) thì hoàn
        tác trọn, không để nháp đảo / dòng / link dở (khuôn W9.5 asset).

        Chứng từ thuộc lô kết chuyển: không đảo lẻ — phải đảo trọn lô qua
        ``vas.closing.entry.action_reverse_entry`` (context
        ``vas_closing_batch_reverse``).
        """
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_("Only posted moves can be reversed."))
        if self.reversal_move_id:
            raise UserError(_("This move is already reversed (%s).", self.reversal_move_id.name))
        if (
            self.closing_entry_id
            and not self.is_reversal
            and not self.env.context.get('vas_closing_batch_reverse')
        ):
            raise UserError(_(
                'Bút toán %(move)s thuộc lô kết chuyển %(entry)s. '
                'Không đảo lẻ một chứng từ trong lô — mở phiếu kết chuyển '
                'và bấm «Đảo» để đảo toàn bộ lô.',
                move=self.display_name,
                entry=self.closing_entry_id.display_name,
            ))

        date = reverse_date or self._reverse_date_for_cancel()

        line_commands = []
        for line in self.line_ids:
            line_commands.append(Command.create({
                'sequence': line.sequence,
                'account_id': line.account_id.id,
                'name': line.name,
                'debit': line.credit,
                'credit': line.debit,
                'currency_id': line.currency_id.id,
                'amount_currency': -(line.amount_currency or 0.0),
                'partner_id': line.partner_id.id,
                'tax_id': line.tax_id.id,
                'tax_status': line.tax_status,
                'analytic_distribution': line.analytic_distribution,
                'pos_session_res_id': line.pos_session_res_id,
                'pos_session_name': line.pos_session_name,
            }))

        # Gắn reversal_move_id TRƯỚC khi post đảo — cutoff exemption truy ngược
        # gốc qua search([('reversal_move_id', '=', reverse.id)]).
        with self.env.cr.savepoint():
            reverse = self.create({
                'date': date,
                'journal_id': self.journal_id.id,
                'regime_id': self.regime_id.id,
                'move_kind': self.move_kind,
                'ref': _('Reversal of %s') % (self.name or ''),
                'is_reversal': True,
                'currency_id': self.currency_id.id,
                'company_id': self.company_id.id,
                'closing_entry_id': self.closing_entry_id.id,
                'narration': self.narration,
                'line_ids': line_commands,
            })
            self.with_context(
                vas_allow_posted_write=True, vas_skip_period_check=True,
            ).write({'reversal_move_id': reverse.id})
            reverse.action_post()
            self.with_context(
                vas_allow_posted_write=True, vas_skip_period_check=True,
            ).write({
                'state': 'reversed',
                'source_cancel_pending': False,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bút toán đảo'),
            'res_model': 'vas.move',
            'res_id': reverse.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_sync_now(self):
        """List-header button: run VAS posting sync for the current company."""
        stats = self.env['vas.sync'].sync_company(self.env.company)
        default_account = stats.pop('default_account', {})
        message = str(stats)
        notification_type = 'success'
        if default_account.get('moves'):
            notification_type = 'warning'
            groups = ', '.join(default_account.get('categories') or []) or _('(không xác định)')
            message = _(
                '%(stats)s\n\n⚠ %(count)s bút toán đang dùng TÀI KHOẢN MẶC ĐỊNH vì '
                'chưa khai ánh xạ. Nhóm cần khai: %(groups)s.\n'
                'Lọc "Dùng TK mặc định" trên màn Bút toán để xem. '
                'Kỳ còn bút toán loại này sẽ không khóa được.',
                stats=stats, count=default_account['moves'], groups=groups,
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đồng bộ VAS'),
                'message': message,
                'type': notification_type,
                'sticky': notification_type == 'warning',
                # Reload current list/controller without full page refresh — keeps
                # active search filters, domain and group-by.
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
