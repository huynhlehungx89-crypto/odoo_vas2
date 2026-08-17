# -*- coding: utf-8 -*-
"""Gợi ý vượt định mức từ BOM — phụ thuộc mềm mrp."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round


class VasVarianceBomHelper(models.AbstractModel):
    _name = 'vas.variance.bom.helper'
    _description = 'Gợi ý BOM vượt định mức (mềm)'

    @api.model
    def _qty_standard(self, bom_qty_per_finished, qty_finished_actual):
        """lượng định mức = định mức BOM / 1 × sản lượng thực tế hoàn thành."""
        return (bom_qty_per_finished or 0.0) * (qty_finished_actual or 0.0)

    @api.model
    def _qty_actual_net(self, qty_out, qty_return):
        """Lượng thực tế = xuất ròng sau hoàn trả."""
        return (qty_out or 0.0) - (qty_return or 0.0)

    @api.model
    def _convert_qty(self, qty, from_uom, to_uom):
        if not from_uom or not to_uom or from_uom == to_uom:
            return qty or 0.0
        return from_uom._compute_quantity(qty or 0.0, to_uom)

    @api.model
    def _excess_amount(self, qty_variance, stock_value, qty_actual):
        """Tiền vượt theo đơn giá xuất thực tế của lần xuất."""
        if float_is_zero(qty_actual or 0.0, precision_digits=6):
            return 0.0
        unit = (stock_value or 0.0) / qty_actual
        return max(qty_variance or 0.0, 0.0) * unit

    @api.model
    def suggest(self, sheet):
        """Điền dòng gợi ý vào phiếu. Trả notification với 4 số đếm."""
        sheet.ensure_one()
        if 'mrp.bom' not in self.env or 'mrp.production' not in self.env:
            raise UserError(_(
                'Chưa cài module MRP — nút «Lấy số gợi ý» chưa dùng được.\n'
                'Vẫn tạo được phiếu thủ công.',
            ))
        Sync = self.env['vas.sync']
        period = sheet.period_id
        n_excess = n_saving = n_insufficient = n_used = 0
        Line = self.env['vas.variance.line']
        # Xóa dòng gợi ý BOM cũ trên phiếu nháp
        sheet.line_ids.filtered(
            lambda l: l.suggestion_source == 'bom',
        ).unlink()

        productions = self.env['mrp.production'].search([
            ('company_id', '=', sheet.company_id.id),
            ('date_finished', '>=', fields.Datetime.to_datetime(
                '%s 00:00:00' % period.date_from,
            )),
            ('date_finished', '<=', fields.Datetime.to_datetime(
                '%s 23:59:59' % period.date_to,
            )),
            ('state', '=', 'done'),
        ])
        # Fallback: date_start nếu không có date_finished
        if not productions:
            productions = self.env['mrp.production'].search([
                ('company_id', '=', sheet.company_id.id),
                ('date_start', '>=', fields.Datetime.to_datetime(
                    '%s 00:00:00' % period.date_from,
                )),
                ('date_start', '<=', fields.Datetime.to_datetime(
                    '%s 23:59:59' % period.date_to,
                )),
                ('state', '=', 'done'),
            ])

        used_move_ids = set(
            Line.search([
                ('source_model', '=', 'stock.move'),
                ('sheet_id.state', 'in', ('confirmed', 'posted')),
                ('sheet_id', '!=', sheet.id),
            ]).mapped('source_res_id')
        )

        for mo in productions:
            bom = mo.bom_id
            if not bom:
                n_insufficient += 1
                continue
            qty_done = mo.qty_produced or mo.product_qty or 0.0
            # Map cost object
            cost_object = self.env['vas.cost.object'].search([
                ('company_id', '=', sheet.company_id.id),
                ('source_model', '=', 'product.product'),
                ('source_res_id', '=', mo.product_id.id),
            ], limit=1)
            if not cost_object and period.cost_object_ids:
                cost_object = period.cost_object_ids[:1]
            if not cost_object:
                n_insufficient += 1
                continue

            # Raw moves: consumption
            raw_moves = mo.move_raw_ids.filtered(lambda m: m.state == 'done')
            for bom_line in bom.bom_line_ids:
                product = bom_line.product_id
                bom_uom = bom_line.product_uom_id
                # qty per finished unit in bom UoM
                bom_qty_per = bom_line.product_qty / (bom.product_qty or 1.0)
                std = self._qty_standard(bom_qty_per, qty_done)

                moves = raw_moves.filtered(lambda m: m.product_id == product)
                if not moves:
                    # Không có xuất — không gợi ý vượt
                    continue
                qty_out = 0.0
                qty_ret = 0.0
                stock_value = 0.0
                primary_move = moves[0]
                for mv in moves:
                    if mv.id in used_move_ids:
                        n_used += 1
                        continue
                    q = mv.quantity or mv.product_uom_qty or 0.0
                    # Convert to bom UoM
                    q_bom = self._convert_qty(q, mv.product_uom, bom_uom)
                    # Return: location dest is production / supplier style
                    if getattr(mv, 'to_refund', False) or (
                        mv.location_dest_id and mv.location_dest_id.usage == 'internal'
                        and mv.location_id and mv.location_id.usage == 'production'
                    ):
                        qty_ret += q_bom
                    else:
                        qty_out += q_bom
                    stock_value += Sync._cogs_amount(mv) or 0.0
                    primary_move = mv
                    used_move_ids.add(mv.id)

                actual = self._qty_actual_net(qty_out, qty_ret)
                variance_qty = actual - std
                rounding = product.uom_id.rounding or 0.0001
                if float_is_zero(variance_qty, precision_rounding=rounding):
                    continue
                if float_compare(variance_qty, 0.0, precision_rounding=rounding) > 0:
                    amt = self._excess_amount(variance_qty, stock_value, actual)
                    Line.create({
                        'sheet_id': sheet.id,
                        'line_kind': 'excess',
                        'suggestion_source': 'bom',
                        'cost_object_id': cost_object.id,
                        'product_id': product.id,
                        'qty_standard': std,
                        'qty_actual': actual,
                        'amount_suggested': amt,
                        'amount_confirmed': amt,
                        'reason': _('Gợi ý từ BOM %s', bom.display_name),
                        'source_model': 'stock.move',
                        'source_res_id': primary_move.id,
                        'source_label': primary_move.display_name,
                        'stock_value_actual': stock_value,
                    })
                    n_excess += 1
                else:
                    Line.create({
                        'sheet_id': sheet.id,
                        'line_kind': 'saving',
                        'suggestion_source': 'bom',
                        'cost_object_id': cost_object.id,
                        'product_id': product.id,
                        'qty_standard': std,
                        'qty_actual': actual,
                        'amount_suggested': 0.0,
                        'amount_confirmed': 0.0,
                        'reason': _('Tiết kiệm so BOM %s', bom.display_name),
                        'source_model': 'stock.move',
                        'source_res_id': primary_move.id,
                        'source_label': primary_move.display_name,
                        'stock_value_actual': stock_value,
                    })
                    n_saving += 1

        if not productions:
            n_insufficient = max(n_insufficient, 1)

        msg = _(
            'Gợi ý xong: vượt %(e)s · tiết kiệm %(s)s · '
            'không đủ dữ liệu %(i)s · đã dùng phiếu khác %(u)s.',
            e=n_excess, s=n_saving, i=n_insufficient, u=n_used,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Lấy số gợi ý'),
                'message': msg,
                'type': 'success' if n_excess or n_saving else 'warning',
                'sticky': False,
            },
            'n_excess': n_excess,
            'n_saving': n_saving,
            'n_insufficient': n_insufficient,
            'n_used': n_used,
        }
