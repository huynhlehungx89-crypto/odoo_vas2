# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class VasCostObjectAssignQueue(models.Model):
    """Hàng chờ gắn đối tượng tập hợp cho xuất NVL SX (R14) khi sync không suy ra được.

    Phase 1b: tạo khi JE NVLTT thiếu đối tượng; gắn tay (kể cả JE đã post, có audit
    qua context ``vas_allow_posted_write``) hoặc bỏ qua.
    Phase 1c: ``action_auto_resolve`` / sync ``backfill_production_cost_objects``.
    """

    _name = 'vas.cost.object.assign.queue'
    _description = 'Hàng chờ gắn đối tượng NVLTT (R14)'
    _order = 'state, id desc'

    company_id = fields.Many2one(
        'res.company', string='Công ty', required=True, index=True,
        default=lambda self: self.env.company,
    )
    move_id = fields.Many2one(
        'vas.move', string='Bút toán', required=True, ondelete='cascade', index=True,
    )
    move_line_id = fields.Many2one(
        'vas.move.line', string='Dòng bút toán', required=True, ondelete='cascade',
        index=True,
    )
    stock_move_id = fields.Many2one(
        'stock.move', string='Phiếu xuất NVL', ondelete='set null', index=True,
    )
    production_name = fields.Char(
        string='Lệnh sản xuất',
        help='Tên MO (mrp không hard-depend — chỉ lưu nhãn).',
    )
    suggested_product_id = fields.Many2one(
        'product.product', string='Thành phẩm gợi ý', ondelete='set null',
        help='Thành phẩm của MO — dùng để tìm / chọn đối tượng loại Sản phẩm.',
    )
    cost_object_id = fields.Many2one(
        'vas.cost.object', string='Đối tượng tập hợp',
        domain="[('company_id', '=', company_id), ('object_type', '=', 'product')]",
        help='Chọn đối tượng rồi bấm Gắn đối tượng.',
    )
    reason = fields.Char(string='Lý do chưa gắn', required=True)
    amount = fields.Monetary(
        string='Số tiền', currency_field='currency_id',
        related='move_line_id.debit', store=True,
    )
    currency_id = fields.Many2one(
        related='move_id.currency_id', store=True,
    )
    state = fields.Selection(
        [
            ('pending', 'Chờ gắn'),
            ('done', 'Đã gắn'),
            ('skipped', 'Bỏ qua'),
        ],
        string='Trạng thái', default='pending', required=True, index=True,
    )
    resolved_uid = fields.Many2one('res.users', string='Người xử lý', readonly=True)
    resolved_date = fields.Datetime(string='Thời điểm xử lý', readonly=True)
    note = fields.Text(string='Ghi chú xử lý', readonly=True)

    @api.model
    def _enqueue(
        self, *, company, move_line, reason,
        stock_move=None, production=None, product=None,
    ):
        """Tạo hoặc cập nhật hàng chờ pending cho một dòng Nợ NVLTT."""
        if not move_line or move_line.cost_object_id:
            return self.browse()
        existing = self.search([
            ('move_line_id', '=', move_line.id),
            ('state', '=', 'pending'),
        ], limit=1)
        vals = {
            'company_id': company.id,
            'move_id': move_line.move_id.id,
            'move_line_id': move_line.id,
            'stock_move_id': stock_move.id if stock_move else False,
            'production_name': (
                production.display_name if production else False
            ),
            'suggested_product_id': product.id if product else False,
            'reason': reason or _('(không rõ)'),
        }
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)

    def action_assign(self):
        """Gắn ``cost_object_id`` lên dòng JE (kể cả đã post) + đóng hàng chờ."""
        for rec in self:
            if rec.state != 'pending':
                raise UserError(_('Chỉ gắn được dòng đang Chờ gắn.'))
            if not rec.cost_object_id:
                raise UserError(_('Chọn đối tượng tập hợp trước khi gắn.'))
            if rec.cost_object_id.company_id != rec.company_id:
                raise UserError(_('Đối tượng phải thuộc cùng công ty với bút toán.'))
            if rec.move_line_id.cost_object_id:
                rec._mark_done(_('Dòng đã có đối tượng — đóng hàng chờ.'))
                continue
            rec.move_line_id.with_context(vas_allow_posted_write=True).write({
                'cost_object_id': rec.cost_object_id.id,
            })
            rec.move_id._refresh_missing_cost_object_flag(
                note=_(
                    'Đã gắn đối tượng %(obj)s từ hàng chờ (dòng %(line)s).',
                    obj=rec.cost_object_id.display_name,
                    line=rec.move_line_id.id,
                ),
            )
            rec._mark_done(_('Gắn tay từ hàng chờ.'))
        return True

    def action_skip(self):
        for rec in self:
            if rec.state != 'pending':
                continue
            rec.write({
                'state': 'skipped',
                'resolved_uid': self.env.uid,
                'resolved_date': fields.Datetime.now(),
                'note': _('Bỏ qua — giữ dòng NVLTT không đối tượng.'),
            })
        return True

    def action_auto_resolve(self):
        """Thử lại thuật toán sync; gắn nếu đúng 1 đối tượng SP."""
        Sync = self.env['vas.sync']
        for rec in self.filtered(lambda r: r.state == 'pending'):
            sm = rec.stock_move_id
            if not sm and rec.move_id.source_model == 'stock.move':
                sm = self.env['stock.move'].browse(rec.move_id.source_res_id).exists()
            if not sm:
                continue
            cost_object = Sync._resolve_production_cost_object(
                sm, rec.company_id, misses=None,
            )
            if not cost_object:
                continue
            rec.cost_object_id = cost_object
            rec.action_assign()
        return True

    def _mark_done(self, note):
        self.ensure_one()
        self.write({
            'state': 'done',
            'resolved_uid': self.env.uid,
            'resolved_date': fields.Datetime.now(),
            'note': note,
        })

    @api.model
    def action_open_pending(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Đối tượng NVLTT chưa gắn'),
            'res_model': 'vas.cost.object.assign.queue',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'pending')],
            'context': {'search_default_pending': 1},
        }
