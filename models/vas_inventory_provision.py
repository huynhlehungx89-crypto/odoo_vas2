# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero


class VasInventoryProvision(models.Model):
    _name = 'vas.inventory.provision'
    _description = 'Phiếu dự phòng giảm giá hàng tồn kho'
    _order = 'date desc, id desc'

    name = fields.Char(string='Số phiếu', required=True, copy=False, default='/')
    date = fields.Date(
        string='Ngày',
        required=True,
        default=fields.Date.context_today,
        index=True,
        help='Thời điểm lập BCTC / đánh giá NRV (TT133 Điều 36).',
    )
    period_id = fields.Many2one(
        'vas.period', string='Kỳ', compute='_compute_period_id', store=True,
    )
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        index=True,
    )
    regime_id = fields.Many2one(
        'vas.regime', string='Chế độ', required=True,
        default=lambda self: self.env.company.vas_regime_id,
    )
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.ref('base.VND'),
        required=True,
    )
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('posted', 'Đã ghi sổ'),
        ('reversed', 'Đã đảo'),
        ('cancelled', 'Đã hủy'),
    ], default='draft', required=True, copy=False, index=True)
    ref = fields.Char(string='Diễn giải')
    line_ids = fields.One2many(
        'vas.inventory.provision.line', 'provision_id', string='Dòng hàng',
        copy=True,
    )
    move_id = fields.Many2one('vas.move', string='Bút toán VAS', copy=False, readonly=True)
    amount_needed = fields.Monetary(
        string='Tổng phải lập', compute='_compute_totals',
        currency_field='currency_id',
    )
    amount_delta = fields.Monetary(
        string='Chênh kỳ này', compute='_compute_totals',
        currency_field='currency_id',
    )

    @api.depends('date', 'company_id')
    def _compute_period_id(self):
        Period = self.env['vas.period']
        for rec in self:
            if not rec.date:
                rec.period_id = False
                continue
            domain = [
                ('date_start', '<=', rec.date),
                ('date_end', '>=', rec.date),
            ]
            if rec.company_id:
                domain.append(('fiscalyear_id.company_id', '=', rec.company_id.id))
            rec.period_id = Period.search(domain, limit=1)

    @api.depends('line_ids.needed', 'line_ids.delta')
    def _compute_totals(self):
        for rec in self:
            rec.amount_needed = sum(rec.line_ids.mapped('needed'))
            rec.amount_delta = sum(rec.line_ids.mapped('delta'))

    def write(self, vals):
        if 'state' in vals and vals['state'] == 'draft':
            locked = self.filtered(lambda r: r.state == 'cancelled')
            if locked:
                raise UserError(_(
                    "Phiếu dự phòng đã hủy không mở lại được. Tạo phiếu mới."
                ))
        posted = self.filtered(lambda r: r.state == 'posted')
        if posted and not self.env.context.get('vas_provision_unlock'):
            allowed = {'state', 'move_id', 'name'}
            if set(vals) - allowed:
                raise UserError(_(
                    "Chứng từ dự phòng đã ghi sổ không sửa được. Phải đảo rồi lập phiếu mới."
                ))
        return super().write(vals)

    def action_refresh_book(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Chỉ phiếu nháp mới lấy lại giá gốc sổ."))
        self.line_ids._refresh_book()
        return True

    def action_post(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Chỉ phiếu nháp mới ghi sổ được."))
            if not rec.line_ids:
                raise UserError(_("Cần ít nhất một dòng hàng."))
            rec.line_ids._refresh_book()
            rec.flush_recordset()
            rec.line_ids._compute_previous_and_delta()
            move = rec._create_vas_move()
            name = rec.name
            if name == '/':
                name = self.env['ir.sequence'].next_by_code(
                    'vas.inventory.provision'
                ) or f'DPHTK/{rec.date}/{rec.id}'
            rec.with_context(vas_provision_unlock=True).write({
                'state': 'posted',
                'move_id': move.id if move else False,
                'name': name,
            })
        return True

    def _previous_balance(self, product):
        self.ensure_one()
        Line = self.env['vas.inventory.provision.line']
        lines = Line.search([
            ('product_id', '=', product.id),
            ('provision_id.company_id', '=', self.company_id.id),
            ('provision_id.state', '=', 'posted'),
            ('provision_id.id', '!=', self.id),
        ])
        if not lines:
            return 0.0
        line = lines.sorted(
            key=lambda l: (l.provision_id.date, l.provision_id.id),
            reverse=True,
        )[0]
        return line.needed or 0.0

    def _create_vas_move(self):
        self.ensure_one()
        acc_632 = self.env['vas.account'].search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', '632'),
        ], limit=1)
        acc_2294 = self.env['vas.account'].search([
            ('regime_id', '=', self.regime_id.id), ('code', '=', '2294'),
        ], limit=1)
        if not acc_632 or not acc_2294:
            raise UserError(_("Thiếu tài khoản VAS 632 hoặc 2294."))
        increase = sum(l.delta for l in self.line_ids if l.delta > 0)
        decrease = sum(-l.delta for l in self.line_ids if l.delta < 0)
        if float_is_zero(increase, 2) and float_is_zero(decrease, 2):
            return self.env['vas.move']
        journal = self.env['vas.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('code', '=', 'TH'),
        ], limit=1) or self.env['vas.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('code', '=', 'KHO'),
        ], limit=1)
        if not journal:
            raise UserError(_("Thiếu sổ nhật ký VAS TH hoặc KHO."))
        from odoo import Command
        cmds = []
        seq = 10
        label = self.ref or _('Dự phòng giảm giá HTK %s') % (self.name,)
        if not float_is_zero(increase, 2):
            cmds.append(Command.create({
                'sequence': seq,
                'account_id': acc_632.id,
                'name': _('Trích thêm dự phòng HTK'),
                'debit': increase,
                'credit': 0.0,
                'currency_id': self.currency_id.id,
            }))
            seq += 10
            cmds.append(Command.create({
                'sequence': seq,
                'account_id': acc_2294.id,
                'name': _('Trích thêm dự phòng HTK'),
                'debit': 0.0,
                'credit': increase,
                'currency_id': self.currency_id.id,
            }))
            seq += 10
        if not float_is_zero(decrease, 2):
            cmds.append(Command.create({
                'sequence': seq,
                'account_id': acc_2294.id,
                'name': _('Hoàn nhập dự phòng HTK'),
                'debit': decrease,
                'credit': 0.0,
                'currency_id': self.currency_id.id,
            }))
            seq += 10
            cmds.append(Command.create({
                'sequence': seq,
                'account_id': acc_632.id,
                'name': _('Hoàn nhập dự phòng HTK'),
                'debit': 0.0,
                'credit': decrease,
                'currency_id': self.currency_id.id,
            }))
        move = self.env['vas.move'].create({
            'date': self.date,
            'journal_id': journal.id,
            'regime_id': self.regime_id.id,
            'move_kind': 'inventory_provision',
            'ref': label,
            'source_model': self._name,
            'source_res_id': self.id,
            'source_ref': self.display_name,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': cmds,
        })
        move.action_post()
        return move

    def action_reverse(self):
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_("Chỉ phiếu đã ghi sổ mới đảo được."))
        move = self.move_id
        Period = self.env['vas.period']
        if move and move.state == 'posted':
            status = Period._coverage_status(move.company_id, move.date)
            if status == 'closed':
                move.with_context(
                    vas_allow_posted_write=True,
                    vas_skip_period_check=True,
                ).write({'source_cancel_pending': True})
                return True
            if status == 'missing':
                Period._raise_missing_period(
                    move.company_id, move.date, doc_name=move.name,
                )
            move.action_reverse()
        self.with_context(vas_provision_unlock=True).write({'state': 'reversed'})
        return True

    def action_cancel(self):
        Period = self.env['vas.period']
        for rec in self:
            if rec.state != 'posted':
                raise UserError(_("Chỉ phiếu đã ghi sổ mới hủy được."))
            move = rec.move_id
            if move and move.state == 'posted':
                status = Period._coverage_status(move.company_id, move.date)
                if status == 'closed':
                    move.with_context(
                        vas_allow_posted_write=True,
                        vas_skip_period_check=True,
                    ).write({'source_cancel_pending': True})
                elif status == 'missing':
                    Period._raise_missing_period(
                        move.company_id, move.date, doc_name=move.name,
                    )
                else:
                    move.action_reverse()
            rec.with_context(vas_provision_unlock=True).write({'state': 'cancelled'})
        return True


class VasInventoryProvisionLine(models.Model):
    _name = 'vas.inventory.provision.line'
    _description = 'Dòng dự phòng giảm giá HTK'
    _order = 'id'

    provision_id = fields.Many2one(
        'vas.inventory.provision', required=True, ondelete='cascade', index=True,
    )
    product_id = fields.Many2one(
        'product.product', string='Sản phẩm', required=True, index=True,
        domain="[('is_storable', '=', True)]",
    )
    book_qty = fields.Float(string='SL tồn sổ', digits='Product Unit')
    book_value = fields.Monetary(
        string='Giá gốc sổ', currency_field='currency_id',
        help='Giá gốc còn lại trên sổ VAS (không đọc giá Odoo).',
    )
    nrv_value = fields.Monetary(
        string='Giá trị thuần có thể thực hiện',
        currency_field='currency_id',
    )
    needed = fields.Monetary(
        string='Phải lập kỳ này', compute='_compute_needed', store=True,
        currency_field='currency_id',
    )
    previous = fields.Monetary(
        string='Đã lập còn hiệu lực', currency_field='currency_id',
    )
    delta = fields.Monetary(
        string='Trích thêm / hoàn nhập', currency_field='currency_id',
    )
    currency_id = fields.Many2one(related='provision_id.currency_id')
    company_id = fields.Many2one(related='provision_id.company_id')

    @api.depends('book_value', 'nrv_value')
    def _compute_needed(self):
        for line in self:
            line.needed = max(0.0, (line.book_value or 0.0) - (line.nrv_value or 0.0))

    @api.onchange('product_id')
    def _onchange_product_id(self):
        self._refresh_book()

    def _refresh_book(self):
        Sync = self.env['vas.sync']
        for line in self:
            if not line.product_id or not line.provision_id.company_id:
                continue
            qty, val = Sync._vas_product_book(
                line.product_id, line.provision_id.company_id,
            )
            line.book_qty = qty
            line.book_value = val

    def _compute_previous_and_delta(self):
        for line in self:
            prev = line.provision_id._previous_balance(line.product_id)
            line.previous = prev
            line.delta = (line.needed or 0.0) - prev

    def write(self, vals):
        if self.provision_id.filtered(lambda p: p.state == 'posted'):
            if not self.env.context.get('vas_provision_unlock'):
                raise UserError(_(
                    "Chứng từ dự phòng đã ghi sổ không sửa được. Phải đảo rồi lập phiếu mới."
                ))
        return super().write(vals)
