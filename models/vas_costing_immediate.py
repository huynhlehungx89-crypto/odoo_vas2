# -*- coding: utf-8 -*-
"""W12 Chặng 5 — ghi tạm thành phẩm (giá NVL) và ghi bù 155/632.

Cổng kiểm dấu vân tay lượt phân bổ (không có tín hiệu tức thời từ Odoo):
  1. Kỳ nhận kết quả phân bổ — ``vas.costing.period.action_receive_allocation``
  2. Mở lại lượt (đưa về nháp) — ``vas.allocation.run.action_set_draft``
  3. Kỳ tính giá thành — ``vas.costing.period.action_compute_costing``
So tại cổng: chụp lại và so với dấu lúc xác nhận; lệch → cần chạy lại + nêu phần lệch.
"""
import math
from datetime import datetime, time

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


class VasCostingProvisionalLot(models.Model):
    """Bản ghi tạm theo lô (phiếu nhập TP) — nguồn tính chênh lệch cuối kỳ."""

    _name = 'vas.costing.provisional.lot'
    _description = 'Ghi tạm thành phẩm theo lô'
    _order = 'receipt_date, lot_code, id'

    name = fields.Char(string='Tên', compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True, ondelete='restrict',
        default=lambda self: self.env.company,
    )
    warehouse_config_id = fields.Many2one(
        'vas.costing.warehouse.config', string='Cấu hình kho',
        required=True, index=True, ondelete='restrict',
    )
    period_id = fields.Many2one(
        'vas.costing.period', string='Kỳ giá thành',
        required=True, index=True, ondelete='restrict',
    )
    cost_object_id = fields.Many2one(
        'vas.cost.object', string='Đối tượng',
        required=True, index=True, ondelete='restrict',
    )
    product_id = fields.Many2one(
        'product.product', string='Sản phẩm',
        required=True, index=True, ondelete='restrict',
    )
    stock_move_id = fields.Many2one(
        'stock.move', string='Phiếu nhập TP (lô)',
        required=True, index=True, ondelete='restrict',
    )
    lot_code = fields.Char(
        string='Mã lô', index=True,
        help='Mã lô stock hoặc mã nội bộ phiếu nhập — dùng hòa phần dư.',
    )
    qty = fields.Float(string='Số lượng', digits='Product Unit of Measure', required=True)
    unit_price_provisional = fields.Monetary(
        string='Đơn giá tạm', currency_field='currency_id',
    )
    amount_provisional = fields.Monetary(
        string='Tổng tiền tạm', currency_field='currency_id', required=True,
    )
    receipt_date = fields.Datetime(string='Ngày nhập kho vật lý', required=True)
    source_kind = fields.Selection(
        selection=[
            ('nvl_stock_value', 'Tiền NVL từ định giá kho'),
            ('nvl_mrp_raw', 'Tiền NVL từ xuất nguyên liệu lệnh SX'),
        ],
        string='Nguồn số tạm', required=True, default='nvl_stock_value',
    )
    move_id = fields.Many2one(
        'vas.move', string='Bút toán ghi tạm',
        ondelete='restrict', copy=False, index=True,
    )
    state = fields.Selection(
        selection=[
            ('posted', 'Đã ghi tạm'),
            ('reversed', 'Đã đảo'),
        ],
        default='posted', required=True, index=True, copy=False,
    )
    amount_official = fields.Monetary(
        string='Giá chính thức giao cho lô', currency_field='currency_id',
        copy=False,
    )
    amount_diff = fields.Monetary(
        string='Chênh lệch lô', currency_field='currency_id', copy=False,
        help='Giá chính thức − số đã ghi tạm.',
    )
    qty_remaining = fields.Float(
        string='SL còn tồn tại ngày cắt', digits='Product Unit of Measure',
        copy=False,
    )
    qty_sold = fields.Float(
        string='SL đã bán tại ngày cắt', digits='Product Unit of Measure',
        copy=False,
    )
    amount_trueup_stock = fields.Monetary(
        string='Bù vào tồn (155)', currency_field='currency_id', copy=False,
    )
    amount_trueup_cogs = fields.Monetary(
        string='Bù vào giá vốn (632)', currency_field='currency_id', copy=False,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id', store=True, readonly=True,
    )

    _stock_move_posted_uniq = models.Constraint(
        'UNIQUE(stock_move_id, state)',
        'Mỗi phiếu nhập thành phẩm chỉ có một bản ghi tạm theo từng trạng thái.',
    )

    @api.depends('stock_move_id', 'lot_code', 'period_id')
    def _compute_name(self):
        for rec in self:
            code = rec.lot_code or (
                rec.stock_move_id.display_name if rec.stock_move_id else '?'
            )
            rec.name = '%s / %s' % (rec.period_id.name or '?', code)

    def action_open_move(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('Lô «%s» chưa có bút toán ghi tạm.', self.display_name))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bút toán ghi tạm'),
            'res_model': 'vas.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_reverse_provisional(self):
        """Đảo ghi tạm — chặn nếu kỳ đã ghi bù còn hiệu lực."""
        for lot in self:
            if lot.state != 'posted':
                raise UserError(_(
                    'Lô «%s» không ở trạng thái Đã ghi tạm.', lot.display_name,
                ))
            period = lot.period_id
            if period.posting_move_id and period.posting_move_id.state == 'posted' \
                    and not period.posting_move_id.is_reversal:
                raise UserError(_(
                    'Không đảo ghi tạm của lô «%(lot)s»: kỳ «%(p)s» đã có bút toán '
                    'ghi bù còn hiệu lực «%(m)s».\n'
                    'Việc cần làm: đảo ghi bù trước (bước đang vướng), rồi mới đảo tạm.',
                    lot=lot.display_name, p=period.display_name,
                    m=period.posting_move_id.display_name,
                ))
            if lot.move_id and lot.move_id.state == 'posted':
                lot.move_id.action_reverse()
            lot.state = 'reversed'
        return True


class VasCostingPeriodImmediate(models.Model):
    _inherit = 'vas.costing.period'

    provisional_lot_ids = fields.One2many(
        'vas.costing.provisional.lot', 'period_id', string='Lô đã ghi tạm',
    )
    posting_mode = fields.Selection(
        selection=[
            ('period_end', 'Ghi cuối kỳ'),
            ('immediate', 'Ghi ngay (giá tạm)'),
            ('mixed', 'Hỗn hợp (không hợp lệ)'),
            ('none', 'Chưa khai kho'),
        ],
        string='Chế độ ghi nhận (từ cấu hình kho)',
        compute='_compute_posting_mode',
    )

    @api.depends('company_id', 'cost_object_ids')
    def _compute_posting_mode(self):
        for period in self:
            configs = period._warehouse_configs()
            if not configs:
                period.posting_mode = 'none'
                continue
            modes = set(configs.mapped('posting_mode'))
            if len(modes) > 1:
                period.posting_mode = 'mixed'
            else:
                period.posting_mode = modes.pop()

    # ------------------------------------------------------------------
    # Giới hạn phiên bản đầu — kỳ trong một kỳ KT còn mở
    # ------------------------------------------------------------------

    def _accounting_periods_covering_costing(self):
        self.ensure_one()
        Period = self.env['vas.period']
        return Period.search([
            ('fiscalyear_id.company_id', '=', self.company_id.id),
            ('date_start', '<=', self.date_to),
            ('date_end', '>=', self.date_from),
        ])

    def _assert_immediate_mode_allowed(self):
        """Chặn ghi ngay nếu kỳ kéo hai kỳ KT hoặc kỳ ghi bù đã khóa."""
        self.ensure_one()
        acc = self._accounting_periods_covering_costing()
        if len(acc) > 1:
            raise UserError(_(
                'Chế độ ghi ngay chưa hỗ trợ kỳ giá thành kéo qua hai kỳ kế toán.\n'
                'Kỳ giá thành: %(dfrom)s → %(dto)s.\n'
                'Kỳ kế toán chạm: %(list)s.\n'
                'Lý do (a): kỳ giá thành phải nằm trọn trong một kỳ kế toán.',
                dfrom=self.date_from, dto=self.date_to,
                list=', '.join(
                    '%s (%s→%s, %s)' % (
                        p.name, p.date_start, p.date_end, p.state,
                    ) for p in acc
                ),
            ))
        if not acc:
            raise UserError(_(
                'Chế độ ghi ngay: không tìm thấy kỳ kế toán bao phủ '
                '%(dfrom)s → %(dto)s. Khai kỳ kế toán trước.',
                dfrom=self.date_from, dto=self.date_to,
            ))
        acc_one = acc[0]
        if acc_one.state == 'closed':
            raise UserError(_(
                'Chế độ ghi ngay: kỳ kế toán dùng để ghi bù đã khóa.\n'
                'Kỳ kế toán: «%(n)s» (%(dfrom)s → %(dto)s, trạng thái %(s)s).\n'
                'Lý do (b): kỳ kế toán ghi bù phải còn mở.',
                n=acc_one.name, dfrom=acc_one.date_start,
                dto=acc_one.date_end, s=acc_one.state,
            ))
        return acc_one

    def _assert_posting_mode_homogeneous(self):
        self.ensure_one()
        mode = self.posting_mode
        if mode == 'mixed':
            raise UserError(_(
                'Kỳ «%s»: các kho đang khai chế độ ghi nhận khác nhau. '
                'Thống nhất ghi cuối kỳ hoặc ghi ngay trước khi chạy.',
                self.display_name,
            ))
        return mode

    # ------------------------------------------------------------------
    # Tài khoản từ cấu hình VAS (không viết cứng mã)
    # ------------------------------------------------------------------

    def _require_product_vas_account(self, product, selector):
        """Tra TK từ vas.account.map — thiếu khai thì chặn (không fallback im lặng)."""
        self.ensure_one()
        Sync = self.env['vas.sync']
        fallbacks = []
        account = Sync._product_account(
            product, selector, self.company_id, fallbacks=fallbacks,
        )
        if fallbacks:
            raise UserError(_(
                'Chưa khai tài khoản VAS «%(sel)s» cho sản phẩm «%(p)s» '
                '(nhóm %(c)s) trên bảng ánh xạ theo chế độ %(r)s.\n'
                'Không dùng mã viết cứng — mở Connecta VAS > Ánh xạ tài khoản.',
                sel=selector, p=product.display_name,
                c=product.categ_id.display_name if product.categ_id else '?',
                r=self.company_id.vas_regime_id.display_name,
            ))
        return account

    def _wip_account_for_object(self, cost_object):
        acc = cost_object.wip_account_id
        if not acc:
            raise UserError(_(
                'Đối tượng «%s» chưa khai tài khoản dở dang (154).',
                cost_object.display_name,
            ))
        return acc

    def _general_journal(self):
        self.ensure_one()
        journal = self.env['vas.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('type', '=', 'general'),
        ], limit=1)
        if not journal:
            raise UserError(_('Thiếu sổ tổng hợp (general) VAS.'))
        return journal

    # ------------------------------------------------------------------
    # Giá tạm = tiền NVL (đường định giá kho đã có)
    # ------------------------------------------------------------------

    def _nvl_amount_for_fg_move(self, fg_move):
        """Tiền nguyên vật liệu cho một phiếu nhập TP — không cộng NC/CPC."""
        Sync = self.env['vas.sync']
        # Soft MRP: cộng giá trị xuất NVL của lệnh
        production = getattr(fg_move, 'production_id', False) or getattr(
            fg_move, 'raw_material_production_id', False,
        )
        if production and 'mrp.production' in self.env:
            raws = production.move_raw_ids.filtered(lambda m: m.state == 'done')
            unvalued = [
                m for m in raws
                if self._is_stock_move_unvalued(m)
            ]
            if unvalued:
                raise UserError(_(
                    'Nguyên vật liệu chưa được định giá — không ghi tạm.\n'
                    'Phiếu nhập TP: %(fg)s.\n'
                    'Phiếu NVL chưa định giá: %(raw)s.',
                    fg=fg_move.display_name,
                    raw=', '.join(m.display_name for m in unvalued[:5]),
                ))
            amount = sum(abs(Sync._cogs_amount(m) or 0.0) for m in raws)
            return amount, 'nvl_mrp_raw'
        if self._is_stock_move_unvalued(fg_move):
            raise UserError(_(
                'Phiếu nhập thành phẩm chưa được định giá — không ghi tạm.\n'
                'Đích danh: %(fg)s (id=%(id)s, ngày %(d)s).',
                fg=fg_move.display_name, id=fg_move.id, d=fg_move.date,
            ))
        return abs(Sync._cogs_amount(fg_move) or 0.0), 'nvl_stock_value'

    def _lot_code_for_move(self, move):
        lots = move.move_line_ids.mapped('lot_id').filtered(lambda l: l)
        if lots:
            return lots[:1].name
        return move.origin or move.reference or ('SM%s' % move.id)

    def _cost_object_for_product(self, product):
        self.ensure_one()
        objs = self.cost_object_ids.filtered(
            lambda o: o.object_type == 'product'
            and o.source_model == 'product.product'
            and o.source_res_id == product.id
        )
        return objs[:1]

    def _fg_candidate_moves(self):
        """Phiếu nhập TP trong kỳ theo bảng khai kho."""
        self.ensure_one()
        Move = self.env['stock.move']
        configs = self._warehouse_configs()
        if not configs:
            return Move.browse()
        dt_from, dt_to = self._period_dt_bounds()
        moves = Move.browse()
        for obj in self.cost_object_ids.filtered(
            lambda o: o.object_type == 'product'
            and o.source_model == 'product.product'
            and o.source_res_id
        ):
            product = self.env['product.product'].browse(obj.source_res_id).exists()
            if product:
                moves |= self._fg_moves_for_product(product, dt_from, dt_to, configs)
        return moves

    # ------------------------------------------------------------------
    # Nút: Ghi tạm thành phẩm
    # ------------------------------------------------------------------

    def action_post_provisional_fg(self):
        """Đường bấm: quét phiếu TP, ghi tạm theo giá NVL — bỏ qua đã ghi, chặn chưa ĐG."""
        self.ensure_one()
        mode = self._assert_posting_mode_homogeneous()
        if mode != 'immediate':
            raise UserError(_(
                'Kỳ «%(p)s» không ở chế độ ghi ngay (đang: %(m)s).\n'
                'Chỉ dùng nút «Ghi tạm thành phẩm» khi cấu hình kho = Ghi ngay.',
                p=self.display_name, m=mode or '?',
            ))
        self._assert_immediate_mode_allowed()
        configs = self._warehouse_configs().filtered(
            lambda c: c.posting_mode == 'immediate',
        )
        if not configs:
            raise UserError(_(
                'Chưa có kho khai chế độ ghi ngay cho công ty này.',
            ))

        already = self.env['vas.costing.provisional.lot'].search([
            ('period_id', '=', self.id),
            ('state', '=', 'posted'),
        ]).mapped('stock_move_id')
        candidates = self._fg_candidate_moves()
        posted_n = skipped_n = blocked_n = 0
        blocked_msgs = []
        created_lots = self.env['vas.costing.provisional.lot']
        journal = self._general_journal()

        for move in candidates.sorted(lambda m: (m.date, m.id)):
            if move in already:
                skipped_n += 1
                continue
            product = move.product_id
            obj = self._cost_object_for_product(product)
            if not obj:
                blocked_n += 1
                blocked_msgs.append(_(
                    'Phiếu %(m)s: sản phẩm không thuộc đối tượng của kỳ.',
                    m=move.display_name,
                ))
                continue
            cfg = configs.filtered(
                lambda c: c.warehouse_id == (
                    move.picking_type_id.warehouse_id
                    or move.location_dest_id.warehouse_id
                )
            )[:1]
            if not cfg:
                cfg = configs[:1]
            try:
                amount, source_kind = self._nvl_amount_for_fg_move(move)
            except UserError as err:
                blocked_n += 1
                blocked_msgs.append(str(err))
                continue
            qty = move.quantity or move.product_uom_qty or 0.0
            if float_is_zero(qty, precision_digits=6):
                skipped_n += 1
                continue
            if float_is_zero(amount, precision_rounding=self.currency_id.rounding):
                # Giá trị thật = 0 có chủ đích (đã định giá) — vẫn ghi tạm 0? Spec:
                # chưa định giá thì chặn; giá 0 đã định giá thì ghi 0.
                pass
            stock_acc = self._require_product_vas_account(product, 'product_inventory')
            wip_acc = self._wip_account_for_object(obj)
            receipt_dt = fields.Datetime.to_datetime(move.date)
            receipt_date = fields.Date.to_date(receipt_dt)
            unit = amount / qty if qty else 0.0
            lot_code = self._lot_code_for_move(move)
            # Tạo lô trước — nguồn bút toán trỏ lô (không đụng unique sync stock.move)
            lot = self.env['vas.costing.provisional.lot'].create({
                'company_id': self.company_id.id,
                'warehouse_config_id': cfg.id,
                'period_id': self.id,
                'cost_object_id': obj.id,
                'product_id': product.id,
                'stock_move_id': move.id,
                'lot_code': lot_code,
                'qty': qty,
                'unit_price_provisional': unit,
                'amount_provisional': amount,
                'receipt_date': receipt_dt,
                'source_kind': source_kind,
                'state': 'posted',
            })
            vas_move = self.env['vas.move'].create({
                'date': receipt_date,
                'journal_id': journal.id,
                'regime_id': self.company_id.vas_regime_id.id,
                'move_kind': 'manual',
                'ref': _('GT tạm %s', lot_code),
                'company_id': self.company_id.id,
                'currency_id': self.currency_id.id,
                'source_model': 'vas.costing.provisional.lot',
                'source_res_id': lot.id,
                'source_ref': 'provisional_fg',
                'line_ids': [
                    (0, 0, {
                        'account_id': stock_acc.id,
                        'name': _('Ghi tạm TP %s', lot_code),
                        'debit': amount if amount > 0 else 0.0,
                        'credit': -amount if amount < 0 else 0.0,
                        'currency_id': self.currency_id.id,
                        'cost_object_id': obj.id,
                    }),
                    (0, 0, {
                        'account_id': wip_acc.id,
                        'name': _('Kết chuyển tạm %s', lot_code),
                        'debit': -amount if amount < 0 else 0.0,
                        'credit': amount if amount > 0 else 0.0,
                        'currency_id': self.currency_id.id,
                        'cost_object_id': obj.id,
                    }),
                ],
            })
            vas_move.action_post()
            lot.move_id = vas_move.id
            created_lots |= lot
            posted_n += 1

        msg = _(
            'Ghi tạm thành phẩm: đã ghi %(p)s · bỏ qua %(s)s · chặn %(b)s.',
            p=posted_n, s=skipped_n, b=blocked_n,
        )
        if blocked_msgs:
            msg = '%s\n%s' % (msg, '\n'.join(blocked_msgs[:10]))
        # Trả về danh sách lô vừa tạo nếu có — để mở bút toán từ màn hình
        if created_lots:
            return {
                'type': 'ir.actions.act_window',
                'name': msg,
                'res_model': 'vas.costing.provisional.lot',
                'view_mode': 'list,form',
                'domain': [('id', 'in', created_lots.ids)],
                'target': 'current',
                'context': {'default_period_id': self.id},
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Ghi tạm thành phẩm'),
                'message': msg,
                'type': 'warning' if blocked_n else 'success',
                'sticky': bool(blocked_n),
            },
        }

    def action_view_provisional_lots(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lô đã ghi tạm'),
            'res_model': 'vas.costing.provisional.lot',
            'view_mode': 'list,form',
            'domain': [('period_id', '=', self.id)],
            'context': {'default_period_id': self.id},
        }

    # ------------------------------------------------------------------
    # Phân giá chính thức xuống lô + tồn/bán tại date_to
    # ------------------------------------------------------------------

    def _allocate_official_to_lots(self, lots, official_total):
        """Phân tiền chính thức theo SL — làm tròn tiền cuối, phần lẻ lớn nhất."""
        self.ensure_one()
        rounding = self.currency_id.rounding or 1.0
        weights = {lot.id: lot.qty for lot in lots}
        denom = sum(weights.values())
        if float_is_zero(denom, precision_digits=10):
            raise UserError(_(
                'Tổng số lượng hoàn thành bằng 0 — không phân giá chính thức xuống lô.'
            ))
        sign = 1.0 if official_total >= 0 else -1.0
        abs_total = abs(official_total)
        exact = {lid: abs_total * (w / denom) for lid, w in weights.items()}
        unit = rounding
        floors = {
            lid: math.floor(exact[lid] / unit + 1e-12) * unit for lid in weights
        }
        assigned = sum(floors.values())
        remain_units = int(round((abs_total - assigned) / unit))
        # Phần lẻ lớn nhất; hòa → mã lô → id nội bộ
        lot_by_id = {lot.id: lot for lot in lots}
        order = sorted(
            weights.keys(),
            key=lambda lid: (
                -(exact[lid] - floors[lid]),
                lot_by_id[lid].lot_code or '',
                lid,
            ),
        )
        shares_abs = dict(floors)
        for lid in order[:remain_units]:
            shares_abs[lid] = shares_abs[lid] + unit
        shares = {lid: sign * shares_abs[lid] for lid in shares_abs}
        # Bất biến 4.6
        got = sum(shares.values())
        if float_compare(got, official_total, precision_rounding=rounding) != 0:
            raise UserError(_(
                'Bất biến 4.6: tổng giá chính thức phân xuống lô (%(g)s) lệch '
                'tổng phiên bản đã duyệt (%(o)s). Lệch %(d)s.',
                g=got, o=official_total, d=got - official_total,
            ))
        # 4.7: một lô không nhận toàn bộ nếu có >1 lô
        if len(lots) > 1:
            for lid, amt in shares.items():
                if float_compare(amt, official_total, precision_rounding=rounding) == 0:
                    raise UserError(_(
                        'Một lô không được nhận toàn bộ giá thành của kỳ. '
                        'Lô %(c)s nhận %(a)s = tổng %(t)s.',
                        c=lot_by_id[lid].lot_code, a=amt, t=official_total,
                    ))
        return shares

    def _customer_out_qty_by_product(self, product, date_from_dt, date_to_dt):
        """SL bán (xuất khách) trong [date_from, date_to] — ngày cắt = date_to kỳ."""
        Move = self.env['stock.move']
        outs = Move.search([
            ('company_id', '=', self.company_id.id),
            ('product_id', '=', product.id),
            ('state', '=', 'done'),
            ('date', '>=', date_from_dt),
            ('date', '<=', date_to_dt),
            ('location_dest_id.usage', '=', 'customer'),
        ])
        return sum(outs.mapped(lambda m: m.quantity or m.product_uom_qty or 0.0))

    def _assign_sold_remaining_fifo(self, lots, cutoff_dt):
        """Gán SL đã bán / còn tồn theo FIFO tại ngày kết thúc kỳ giá thành."""
        self.ensure_one()
        by_product = {}
        for lot in lots:
            by_product.setdefault(lot.product_id.id, self.env['vas.costing.provisional.lot'])
            by_product[lot.product_id.id] |= lot
        result = {}
        for product_id, product_lots in by_product.items():
            ordered = product_lots.sorted(
                lambda l: (l.receipt_date, l.lot_code or '', l.id),
            )
            first_dt = ordered[0].receipt_date
            sold_total = self._customer_out_qty_by_product(
                ordered[0].product_id, first_dt, cutoff_dt,
            )
            remaining_to_assign = sold_total
            for lot in ordered:
                take = min(lot.qty, max(remaining_to_assign, 0.0))
                qty_sold = take
                qty_rem = lot.qty - qty_sold
                result[lot.id] = (qty_rem, qty_sold)
                remaining_to_assign -= take
        return result

    def _split_lot_diff_stock_cogs(self, lot_diff, qty_rem, qty_sold, rounding):
        """Chia chênh lệch lô theo tỷ lệ tồn/bán — làm tròn tiền cuối."""
        qty_total = qty_rem + qty_sold
        if float_is_zero(qty_total, precision_digits=6):
            return 0.0, 0.0
        if float_is_zero(qty_sold, precision_digits=6):
            return lot_diff, 0.0
        if float_is_zero(qty_rem, precision_digits=6):
            return 0.0, lot_diff
        # Largest remainder trên 2 đích
        weights = {'stock': qty_rem, 'cogs': qty_sold}
        sign = 1.0 if lot_diff >= 0 else -1.0
        abs_total = abs(lot_diff)
        exact = {k: abs_total * (w / qty_total) for k, w in weights.items()}
        unit = rounding or 1.0
        floors = {
            k: math.floor(exact[k] / unit + 1e-12) * unit for k in weights
        }
        assigned = sum(floors.values())
        remain_units = int(round((abs_total - assigned) / unit))
        order = sorted(
            weights.keys(),
            key=lambda k: (-(exact[k] - floors[k]), k),
        )
        shares = dict(floors)
        for k in order[:remain_units]:
            shares[k] = shares[k] + unit
        return sign * shares['stock'], sign * shares['cogs']

    # ------------------------------------------------------------------
    # Ghi bù (thay thế action_post_costing khi chế độ immediate)
    # ------------------------------------------------------------------

    def _action_post_trueup_immediate(self):
        """Ghi bù sau duyệt — chia 155 (tồn) / 632 (đã bán) tại date_to."""
        self.ensure_one()
        self._assert_immediate_mode_allowed()
        ver = self._assert_post_conditions()
        lots = self.provisional_lot_ids.filtered(lambda l: l.state == 'posted')
        # Loại trừ bút toán tạm đã đảo khi lấy lại dữ liệu
        lots = lots.filtered(
            lambda l: l.move_id
            and l.move_id.state == 'posted'
            and not l.move_id.is_reversal
        )
        if not lots:
            raise UserError(_(
                'Chế độ ghi ngay: chưa có lô ghi tạm còn hiệu lực để ghi bù.\n'
                'Bấm «Ghi tạm thành phẩm» trước.',
            ))

        # Không một lô nuốt hết: phân theo đối tượng
        rounding = self.currency_id.rounding or 1.0
        cutoff_dt = datetime.combine(self.date_to, time.max)
        official_total = ver.total_cost

        # Phân theo từng đối tượng rồi gộp — dòng kết quả chưa gồm opening trên header
        all_shares = {}
        lines_sum = sum(ver.line_ids.mapped('total_cost'))
        for obj in lots.mapped('cost_object_id'):
            obj_lots = lots.filtered(lambda l, o=obj: l.cost_object_id == o)
            line = ver.line_ids.filtered(lambda l, o=obj: l.cost_object_id == o)
            line_amt = sum(line.mapped('total_cost')) if line else 0.0
            if float_is_zero(lines_sum, precision_rounding=rounding):
                qty_all = sum(lots.mapped('qty')) or 1.0
                obj_official = official_total * (sum(obj_lots.mapped('qty')) / qty_all)
            else:
                # Cộng phần dở dang đầu kỳ trên header phiên bản theo tỷ trọng dòng
                opening_share = ver.opening_wip * (line_amt / lines_sum)
                obj_official = line_amt + opening_share
            shares = self._allocate_official_to_lots(obj_lots, obj_official)
            all_shares.update(shares)

        # Bất biến 4.6 toàn kỳ
        got = sum(all_shares.values())
        if float_compare(got, official_total, precision_rounding=rounding) != 0:
            raise UserError(_(
                'Bất biến 4.6: tổng phân xuống mọi lô (%(g)s) lệch tổng đã duyệt '
                '(%(o)s). Lệch %(d)s.',
                g=got, o=official_total, d=got - official_total,
            ))

        sold_map = self._assign_sold_remaining_fifo(lots, cutoff_dt)
        stock_total = 0.0
        cogs_total = 0.0
        for lot in lots:
            official = all_shares[lot.id]
            diff = official - lot.amount_provisional
            qty_rem, qty_sold = sold_map[lot.id]
            tu_stock, tu_cogs = self._split_lot_diff_stock_cogs(
                diff, qty_rem, qty_sold, rounding,
            )
            lot.write({
                'amount_official': official,
                'amount_diff': diff,
                'qty_remaining': qty_rem,
                'qty_sold': qty_sold,
                'amount_trueup_stock': tu_stock,
                'amount_trueup_cogs': tu_cogs,
            })
            stock_total += tu_stock
            cogs_total += tu_cogs

        # Đẳng thức 5.5
        prov_sum = sum(lots.mapped('amount_provisional'))
        trueup_sum = stock_total + cogs_total
        check = prov_sum + trueup_sum
        if float_compare(check, official_total, precision_rounding=rounding) != 0:
            raise UserError(_(
                'Đẳng thức 5.5 lệch: tổng ghi tạm (%(p)s) + tổng ghi bù (%(t)s) '
                '= %(s)s ≠ giá chính thức đã duyệt (%(o)s). Lệch %(d)s.',
                p=prov_sum, t=trueup_sum, s=check, o=official_total,
                d=check - official_total,
            ))

        # Gom bút toán theo sản phẩm (TK có thể khác nhau)
        journal = self._general_journal()
        line_cmds = []
        # Nhóm theo (stock_acc, wip_acc) và (cogs_acc, wip_acc)
        stock_groups = {}
        cogs_groups = {}
        for lot in lots:
            wip = self._wip_account_for_object(lot.cost_object_id)
            if not float_is_zero(lot.amount_trueup_stock, precision_rounding=rounding):
                stock_acc = self._require_product_vas_account(
                    lot.product_id, 'product_inventory',
                )
                key = (stock_acc.id, wip.id)
                stock_groups[key] = stock_groups.get(key, 0.0) + lot.amount_trueup_stock
            if not float_is_zero(lot.amount_trueup_cogs, precision_rounding=rounding):
                cogs_acc = self._require_product_vas_account(
                    lot.product_id, 'product_cogs',
                )
                key = (cogs_acc.id, wip.id)
                cogs_groups[key] = cogs_groups.get(key, 0.0) + lot.amount_trueup_cogs

        def _append_pair(dest_acc_id, wip_id, amount, label_dest, label_wip):
            if float_is_zero(amount, precision_rounding=rounding):
                return
            dest = self.env['vas.account'].browse(dest_acc_id)
            wip = self.env['vas.account'].browse(wip_id)
            if amount > 0:
                # Ghi thêm: Nợ đích / Có 154
                line_cmds.append((0, 0, {
                    'account_id': dest.id, 'name': label_dest,
                    'debit': amount, 'credit': 0.0,
                    'currency_id': self.currency_id.id,
                }))
                line_cmds.append((0, 0, {
                    'account_id': wip.id, 'name': label_wip,
                    'debit': 0.0, 'credit': amount,
                    'currency_id': self.currency_id.id,
                }))
            else:
                # Ghi ngược: Nợ 154 / Có đích
                amt = abs(amount)
                line_cmds.append((0, 0, {
                    'account_id': wip.id, 'name': label_wip,
                    'debit': amt, 'credit': 0.0,
                    'currency_id': self.currency_id.id,
                }))
                line_cmds.append((0, 0, {
                    'account_id': dest.id, 'name': label_dest,
                    'debit': 0.0, 'credit': amt,
                    'currency_id': self.currency_id.id,
                }))

        for (dest_id, wip_id), amount in stock_groups.items():
            _append_pair(
                dest_id, wip_id, amount,
                _('Ghi bù tồn TP %s', self.name),
                _('Kết chuyển bù tồn %s', self.name),
            )
        for (dest_id, wip_id), amount in cogs_groups.items():
            _append_pair(
                dest_id, wip_id, amount,
                _('Ghi bù giá vốn %s', self.name),
                _('Kết chuyển bù GV %s', self.name),
            )

        if not line_cmds:
            # Chênh lệch = 0: vẫn cần bút toán B3 còn hiệu lực
            sample = lots[0]
            stock_acc = self._require_product_vas_account(
                sample.product_id, 'product_inventory',
            )
            wip = self._wip_account_for_object(sample.cost_object_id)
            line_cmds = [
                (0, 0, {
                    'account_id': stock_acc.id,
                    'name': _('Ghi bù (chênh = 0) %s', self.name),
                    'debit': 0.0, 'credit': 0.0,
                    'currency_id': self.currency_id.id,
                }),
                (0, 0, {
                    'account_id': wip.id,
                    'name': _('Kết chuyển bù (chênh = 0) %s', self.name),
                    'debit': 0.0, 'credit': 0.0,
                    'currency_id': self.currency_id.id,
                }),
            ]

        move = self.env['vas.move'].create({
            'date': self.date_to,
            'journal_id': journal.id,
            'regime_id': self.company_id.vas_regime_id.id,
            'move_kind': 'manual',
            'ref': _('GT bù %s', self.name),
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'source_model': 'vas.costing.result.version',
            'source_res_id': ver.id,
            'source_ref': 'costing_trueup',
            'line_ids': line_cmds,
        })
        move.action_post()
        ver.move_id = move.id
        self.write({
            'posting_move_id': move.id,
            'state': 'posted',
        })
        return True
