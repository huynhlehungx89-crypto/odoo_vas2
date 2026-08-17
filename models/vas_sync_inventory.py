# -*- coding: utf-8 -*-
"""Giá vốn trả hàng (lô xuất gốc) + hủy hàng (FIFO còn tồn trên sổ VAS)."""
from datetime import datetime, time

from odoo import _, fields, models
from odoo.tools.float_utils import float_is_zero


class VasSyncInventory(models.AbstractModel):
    _inherit = 'vas.sync'

    def _stock_move_qty(self, stock_move):
        return abs(stock_move.quantity or stock_move.product_uom_qty or 0.0)

    def _pos_order_of_stock_move(self, stock_move):
        picking = stock_move.picking_id
        if picking and 'pos_order_id' in picking._fields and picking.pos_order_id:
            return picking.pos_order_id
        return self.env['pos.order'] if 'pos.order' in self.env else False

    def _vas_live_moves(self, source_model, source_res_id, move_kinds):
        kinds = move_kinds if isinstance(move_kinds, (list, tuple)) else [move_kinds]
        return self.env['vas.move'].search([
            ('source_model', '=', source_model),
            ('source_res_id', '=', source_res_id),
            ('move_kind', 'in', list(kinds)),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ])

    def _vas_move_debit_total(self, moves):
        return sum(moves.mapped(lambda m: sum(m.line_ids.mapped('debit'))))

    def _vas_cogs_posted_amount(self, origin_sm):
        """Giá vốn đã ghi sổ VAS của phiếu xuất gốc — không đọc stock.move.value."""
        live = self._vas_live_moves('stock.move', origin_sm.id, ['cogs'])
        if live:
            return self._vas_move_debit_total(live)
        order = self._pos_order_of_stock_move(origin_sm)
        if order:
            live = self._vas_live_moves('pos.order', order.id, ['pos_cogs'])
            if not live:
                return 0.0
            total = self._vas_move_debit_total(live)
            same = self._pos_order_stock_moves(order).filtered(
                lambda m: m.product_id == origin_sm.product_id
            )
            orig_qty = self._stock_move_qty(origin_sm)
            order_qty = sum(self._stock_move_qty(m) for m in same) or orig_qty
            if order_qty:
                return total * orig_qty / order_qty
            return total
        return 0.0

    def _origin_qty_already_returned_on_books(self, origin, exclude_sm=None):
        qty = 0.0
        returns = origin.returned_move_ids.filtered(lambda m: m.state == 'done')
        if exclude_sm:
            returns -= exclude_sm
        for ret in returns:
            if self._already_synced('stock.move', ret.id, 'stock'):
                qty += self._stock_move_qty(ret)
                continue
            order = self._pos_order_of_stock_move(ret)
            if order and self._already_synced('pos.order', order.id, 'pos_cogs'):
                qty += self._stock_move_qty(ret)
        return qty

    def _pos_refund_origin_cogs_amount(self, refund_order, stock_move, fallbacks=None, notes=None):
        """Giá vốn trả quầy — chỉ qua refunded_order_id / refunded_orderline_id.

        Không đoán LIFO giữa nhiều đơn. Thiếu liên kết đơn gốc → 0 + cờ.
        """
        qty_ret = self._stock_move_qty(stock_move)
        if float_is_zero(qty_ret, 2):
            return 0.0
        # Ưu tiên origin_returned_move_id nếu Odoo đã gắn trên phiếu kho.
        if stock_move.origin_returned_move_id:
            return self._sale_return_origin_cogs(stock_move, fallbacks, notes)
        origin_order = refund_order.refunded_order_id
        if not origin_order:
            label = _(
                'Đơn trả quầy %(order)s — thiếu refunded_order_id / '
                'origin_returned_move_id, không đoán giá (ghi 0)',
                order=refund_order.display_name,
            )
            if fallbacks is not None:
                fallbacks.append({'label': label})
            if notes is not None:
                notes.append(label)
            return 0.0
        origin_val = self._vas_move_debit_total(
            self._vas_live_moves('pos.order', origin_order.id, ['pos_cogs'])
        )
        origin_moves = self._pos_order_stock_moves(origin_order).filtered(
            lambda m: m.product_id == stock_move.product_id
        )
        origin_qty = sum(self._stock_move_qty(m) for m in origin_moves)
        if float_is_zero(origin_val, 2) or float_is_zero(origin_qty, 2):
            label = _(
                'Đơn trả quầy %(order)s — đơn gốc %(origin)s chưa có giá vốn '
                'VAS / SL gốc = 0, không đoán giá (ghi 0)',
                order=refund_order.display_name,
                origin=origin_order.display_name,
            )
            if fallbacks is not None:
                fallbacks.append({'label': label})
            if notes is not None:
                notes.append(label)
            return 0.0
        # Tỷ lệ theo SP trên đúng một đơn gốc (refunded_order_id).
        take = min(qty_ret, origin_qty)
        take_val = origin_val * take / origin_qty
        if notes is not None:
            notes.append(_(
                'Đơn gốc quầy %(origin)s: SL %(qty)s × giá vốn gốc → %(amount)s',
                origin=origin_order.display_name,
                qty=take,
                amount=round(take_val, 2),
            ))
        unmatched = qty_ret - take
        if unmatched > 1e-6:
            label = _(
                'Đơn trả quầy %(order)s — vượt SL còn lại của đơn gốc '
                '%(origin)s (%(qty)s sp), không đoán thêm (phần thừa ghi 0)',
                order=refund_order.display_name,
                origin=origin_order.display_name,
                qty=unmatched,
            )
            if fallbacks is not None:
                fallbacks.append({'label': label})
            if notes is not None:
                notes.append(label)
        return take_val

    def _sale_return_untraced_label(self, return_move, qty):
        picking = return_move.picking_id
        pick_name = (
            picking.display_name if picking else return_move.display_name
        )
        return _(
            'Phiếu kho %(pick)s — không truy được xuất bán gốc '
            '(thiếu origin_returned_move_id) cho %(qty)s sp, '
            'không đoán giá (ghi 0)',
            pick=pick_name,
            qty=qty,
        )

    def _sale_return_origin_cogs(self, return_move, fallbacks=None, notes=None):
        """Giá vốn lúc xuất của lô trả — chỉ qua origin_returned_move_id.

        Không LIFO/FIFO/đoán lô. Thiếu liên kết gốc → 0 + cờ mặc định
        (fallbacks) + ghi chú, chặn khóa kỳ; kế toán sửa chứng từ.
        """
        qty_ret = self._stock_move_qty(return_move)
        if float_is_zero(qty_ret, 2):
            return 0.0
        origin = return_move.origin_returned_move_id
        if not origin or origin.state != 'done':
            label = self._sale_return_untraced_label(return_move, qty_ret)
            if fallbacks is not None:
                fallbacks.append({'label': label})
            if notes is not None:
                notes.append(label)
            return 0.0
        orig_qty = self._stock_move_qty(origin)
        orig_val = self._vas_cogs_posted_amount(origin)
        if float_is_zero(orig_qty, 2) or float_is_zero(orig_val, 2):
            label = self._sale_return_untraced_label(return_move, qty_ret)
            if fallbacks is not None:
                fallbacks.append({'label': label})
            if notes is not None:
                notes.append(label)
            return 0.0
        used = self._origin_qty_already_returned_on_books(
            origin, exclude_sm=return_move,
        )
        avail_qty = orig_qty - used
        if avail_qty <= 1e-9:
            label = self._sale_return_untraced_label(return_move, qty_ret)
            if fallbacks is not None:
                fallbacks.append({'label': label})
            if notes is not None:
                notes.append(label)
            return 0.0
        take = min(qty_ret, avail_qty)
        take_val = orig_val * take / orig_qty
        if notes is not None:
            notes.append(_(
                'Lô xuất %(origin)s: SL %(qty)s × giá vốn gốc → %(amount)s',
                origin=origin.display_name or origin.reference or origin.id,
                qty=take,
                amount=round(take_val, 2),
            ))
        unmatched = qty_ret - take
        if unmatched > 1e-6:
            # Trả vượt phần còn lại của đúng một lô gốc — không đoán lô khác.
            label = self._sale_return_untraced_label(return_move, unmatched)
            if fallbacks is not None:
                fallbacks.append({'label': label})
            if notes is not None:
                notes.append(label)
        return take_val

    def _vas_inventory_cost_events(self, product, company, exclude=None):
        """Sự kiện nhập/xuất đã ghi sổ VAS, theo ngày, để FIFO lớp còn tồn."""
        events = []

        def live(model, res_id, kinds):
            if exclude and exclude == (model, res_id):
                return self.env['vas.move']
            return self._vas_live_moves(model, res_id, kinds)

        def add(date, mid, direction, qty, value):
            if float_is_zero(qty, 2) and float_is_zero(value, 2):
                return
            events.append({
                'date': date or fields.Date.context_today(self),
                'id': mid or 0,
                'direction': direction,
                'qty': abs(qty),
                'value': abs(value),
            })

        moves = self.env['stock.move'].search([
            ('product_id', '=', product.id),
            ('company_id', '=', company.id),
            ('state', '=', 'done'),
        ])
        seen_scrap = set()
        for sm in moves:
            qty = self._stock_move_qty(sm)
            date = self._source_date(sm)
            if sm.scrap_id:
                scrap = sm.scrap_id
                if scrap.id in seen_scrap:
                    continue
                seen_scrap.add(scrap.id)
                vm = live('stock.scrap', scrap.id, ['scrap'])
                if vm:
                    add(date, vm[:1].id, 'out', qty, self._vas_move_debit_total(vm))
                continue
            if sm.location_dest_usage == 'customer':
                vm = live('stock.move', sm.id, ['cogs'])
                if vm:
                    add(date, vm[:1].id, 'out', qty, self._vas_move_debit_total(vm))
                    continue
                order = self._pos_order_of_stock_move(sm)
                if order:
                    vm = live('pos.order', order.id, ['pos_cogs'])
                    if vm:
                        val = self._vas_cogs_posted_amount(sm)
                        direction = (
                            'in' if self._pos_order_is_refund(order) else 'out'
                        )
                        add(date, vm[:1].id, direction, qty, val)
                continue
            if (
                sm.location_usage in ('supplier', 'customer')
                and sm.location_dest_usage == 'internal'
            ):
                vm = live('stock.move', sm.id, ['stock'])
                if vm:
                    add(date, vm[:1].id, 'in', qty, self._vas_move_debit_total(vm))
                continue
            if sm.location_dest_usage == 'supplier':
                vm = live('stock.move', sm.id, ['stock'])
                if vm:
                    add(date, vm[:1].id, 'out', qty, self._vas_move_debit_total(vm))
                continue
            if (
                'raw_material_production_id' in sm._fields
                and sm.raw_material_production_id
            ):
                vm = live('stock.move', sm.id, ['stock'])
                if vm:
                    add(date, vm[:1].id, 'out', qty, self._vas_move_debit_total(vm))

        scraps = self.env['stock.scrap'].search([
            ('product_id', '=', product.id),
            ('company_id', '=', company.id),
            ('state', '=', 'done'),
        ])
        for scrap in scraps:
            if scrap.id in seen_scrap:
                continue
            vm = live('stock.scrap', scrap.id, ['scrap'])
            if vm:
                add(
                    self._source_date(scrap),
                    vm[:1].id,
                    'out',
                    scrap.scrap_qty,
                    self._vas_move_debit_total(vm),
                )
        events.sort(key=lambda e: (e['date'], e['id']))
        return events

    def _vas_fifo_remaining_layers(self, product, company, exclude=None):
        layers = []
        for ev in self._vas_inventory_cost_events(product, company, exclude):
            if ev['direction'] == 'in':
                qty = ev['qty']
                unit = (ev['value'] / qty) if qty else 0.0
                if qty:
                    layers.append({'qty': qty, 'unit': unit})
                continue
            need = ev['qty']
            i = 0
            while need > 1e-9 and i < len(layers):
                take = min(need, layers[i]['qty'])
                layers[i]['qty'] -= take
                need -= take
                if layers[i]['qty'] <= 1e-9:
                    i += 1
            layers = [layer for layer in layers if layer['qty'] > 1e-9]
        return layers

    def _vas_product_book(self, product, company, exclude=None):
        layers = self._vas_fifo_remaining_layers(product, company, exclude)
        qty = sum(layer['qty'] for layer in layers)
        value = sum(layer['qty'] * layer['unit'] for layer in layers)
        return qty, value

    def _fifo_take_cost(self, layers, qty):
        need = qty
        cost = 0.0
        for layer in layers:
            if need <= 1e-9:
                break
            take = min(need, layer['qty'])
            cost += take * layer['unit']
            need -= take
        return cost, max(need, 0.0)

    def _scrap_lot_cost(self, scrap, fallbacks=None):
        qty = abs(scrap.scrap_qty or 0.0)
        if float_is_zero(qty, 2):
            return 0.0
        layers = self._vas_fifo_remaining_layers(
            scrap.product_id, scrap.company_id,
            exclude=('stock.scrap', scrap.id),
        )
        cost, unmatched = self._fifo_take_cost(layers, qty)
        if unmatched > 1e-6 and fallbacks is not None:
            fallbacks.append({
                'label': _(
                    'Phiếu hủy %(scrap)s — không đủ lớp giá vốn sổ VAS cho '
                    '%(qty)s sp, không đoán giá (phần thiếu ghi 0)',
                    scrap=scrap.display_name,
                    qty=unmatched,
                ),
            })
        if float_is_zero(cost, 2) and fallbacks is not None:
            fallbacks.append({
                'label': _(
                    'Phiếu hủy %(scrap)s — không truy được giá vốn lô trên sổ VAS, '
                    'không đoán giá (ghi 0)',
                    scrap=scrap.display_name,
                ),
            })
        return cost

    def _scrap_expense_account(self, company, fallbacks=None):
        """Đối ứng hủy hàng: chỉ TK đã khai. Trống → 811 + cờ (không đoán 632/154/138)."""
        if company.vas_scrap_account_id:
            return company.vas_scrap_account_id, False
        acc = self._account_by_code(company.vas_regime_id, '811')
        if fallbacks is not None:
            fallbacks.append({
                'label': _(
                    'Chưa khai TK đối ứng hủy hàng — dùng %(code)s',
                    code=acc.code if acc else '811',
                ),
            })
        return acc, True

    def _sync_stock_scraps(self, company, date_from, date_to):
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'done'),
        ]
        if date_from:
            domain.append(('date_done', '>=', date_from))
        if date_to:
            end = datetime.combine(fields.Date.to_date(date_to), time.max)
            domain.append(('date_done', '<=', end))
        scraps = self.env['stock.scrap'].search(domain)
        return self._apply_event('stock_scrap', scraps, company)
