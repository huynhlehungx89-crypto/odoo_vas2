# -*- coding: utf-8 -*-
"""Danh mục khoản mục chi phí (W12 Chặng 1A)."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class VasCostItem(models.Model):
    _name = 'vas.cost.item'
    _description = 'Khoản mục chi phí'
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_name = 'complete_name'
    _order = 'complete_name, id'

    code = fields.Char(string='Mã', required=True, index=True)
    name = fields.Char(string='Tên', required=True, translate=False)
    complete_name = fields.Char(
        string='Tên đầy đủ',
        compute='_compute_complete_name',
        recursive=True,
        store=True,
    )
    parent_id = fields.Many2one(
        'vas.cost.item',
        string='Khoản mục cha',
        index=True,
        ondelete='restrict',
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many(
        'vas.cost.item', 'parent_id', string='Khoản mục con',
    )
    account_id = fields.Many2one(
        'vas.account',
        string='Tài khoản',
        required=True,
        ondelete='restrict',
        default=lambda self: self._default_account_154(),
    )
    factor_group = fields.Selection(
        selection=[
            ('material', 'Nguyên vật liệu'),
            ('labor', 'Nhân công'),
            ('depreciation', 'Khấu hao'),
            ('outsourced', 'Mua ngoài'),
            ('other', 'Khác'),
        ],
        string='Nhóm yếu tố',
    )
    note = fields.Text(string='Diễn giải')
    active = fields.Boolean(string='Đang dùng', default=True)
    is_system = fields.Boolean(
        string='Hệ thống',
        default=False,
        copy=False,
        help='Bản ghi gieo sẵn của module — không xóa, không hạ nhãn hệ thống; cho đổi tên.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        required=True,
        index=True,
        ondelete='restrict',
        default=lambda self: self.env.company,
    )
    is_aggregate_node = fields.Boolean(
        string='Nút tổng hợp',
        compute='_compute_is_aggregate_node',
        store=True,
        help='Có con → nút tổng hợp, không nhận bút toán mới. Lá thì ngược lại.',
    )
    has_direct_history = fields.Boolean(
        string='Bút toán lịch sử trực tiếp',
        compute='_compute_direct_history',
        help='Nút tổng hợp từng là lá còn dòng bút toán trỏ thẳng vào nó.',
    )
    direct_history_line_count = fields.Integer(
        string='Số dòng lịch sử trực tiếp',
        compute='_compute_direct_history',
    )
    direct_history_amount = fields.Monetary(
        string='Tổng tiền lịch sử trực tiếp',
        compute='_compute_direct_history',
        currency_field='company_currency_id',
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
    )

    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        'Mã khoản mục chi phí phải duy nhất theo công ty.',
    )

    # Field cấu trúc — seed không được đổi (cho đổi name / note / active).
    _SEED_STRUCTURAL_FIELDS = frozenset({
        'code', 'parent_id', 'account_id', 'factor_group',
        'company_id', 'is_system',
    })

    # Bốn khoản mục hệ thống — seed XML chỉ tạo cho main_company; công ty khác gọi helper.
    _SYSTEM_COST_ITEM_SEEDS = (
        ('NVLTT', 'Nguyên vật liệu trực tiếp', 'material'),
        ('NCTT', 'Nhân công trực tiếp', 'labor'),
        ('CPC', 'Chi phí sản xuất chung', 'other'),
        ('CPD', 'Chưa phân loại', 'other'),
    )

    @api.model
    def _default_account_154(self):
        company = self.env.company
        regime = company.vas_regime_id
        if not regime:
            return False
        return self.env['vas.account'].search([
            ('regime_id', '=', regime.id),
            ('code', '=', '154'),
        ], limit=1)

    @api.model
    def _ensure_system_items_for_company(self, company):
        """Idempotent: đủ NVLTT/NCTT/CPC/CPD cho một công ty (giống journals)."""
        company.ensure_one()
        regime = company.vas_regime_id
        if not regime:
            return self.browse()
        account_154 = self.env['vas.account'].search([
            ('regime_id', '=', regime.id),
            ('code', '=', '154'),
        ], limit=1)
        if not account_154:
            return self.browse()
        created = self.browse()
        for code, name, factor_group in self._SYSTEM_COST_ITEM_SEEDS:
            item = self.with_context(active_test=False).search([
                ('code', '=', code),
                ('company_id', '=', company.id),
            ], limit=1)
            if item:
                continue
            created |= self.create({
                'code': code,
                'name': name,
                'factor_group': factor_group,
                'account_id': account_154.id,
                'company_id': company.id,
                'is_system': True,
                'active': True,
            })
        return created

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for item in self:
            if item.parent_id:
                item.complete_name = '%s / %s' % (
                    item.parent_id.complete_name, item.name,
                )
            else:
                item.complete_name = item.name

    @api.depends('child_ids')
    def _compute_is_aggregate_node(self):
        for item in self:
            item.is_aggregate_node = bool(item.child_ids)

    def _direct_history_lines(self):
        """Dòng bút toán đã vào sổ trỏ THẲNG vào khoản mục này (không gồm đảo)."""
        self.ensure_one()
        return self.env['vas.move.line'].search([
            ('cost_item_id', '=', self.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.is_reversal', '=', False),
        ])

    def _compute_direct_history(self):
        # Non-stored: đọc lại mỗi lần (dòng bút toán đổi không đi qua child_ids).
        grouped = {}
        if self.ids:
            self.env.cr.execute(
                """
                SELECT ml.cost_item_id,
                       COUNT(ml.id),
                       COALESCE(SUM(ml.debit - ml.credit), 0)
                  FROM vas_move_line ml
                  JOIN vas_move m ON m.id = ml.move_id
                 WHERE ml.cost_item_id = ANY(%s)
                   AND m.state = 'posted'
                   AND COALESCE(m.is_reversal, false) = false
                 GROUP BY ml.cost_item_id
                """,
                [list(self.ids)],
            )
            grouped = {
                row[0]: (row[1], row[2]) for row in self.env.cr.fetchall()
            }
        for item in self:
            count, amount = grouped.get(item.id, (0, 0.0))
            item.direct_history_line_count = count
            item.direct_history_amount = amount
            item.has_direct_history = bool(count) and item.is_aggregate_node

    @api.model
    def _system_by_code(self, company, code):
        """Bản ghi hệ thống theo mã trong công ty (NVLTT/NCTT/CPC/CPD)."""
        return self.search([
            ('code', '=', code),
            ('company_id', '=', company.id),
        ], limit=1)

    def get_rollup_posted_amount(self):
        """Số tại nút = lịch sử trỏ TRỰC TIẾP + số TOÀN BỘ các con (mỗi dòng 1 lần)."""
        self.ensure_one()
        lines = self._direct_history_lines()
        direct = sum(lines.mapped(lambda l: l.debit - l.credit))
        children = sum(
            child.get_rollup_posted_amount() for child in self.child_ids
        )
        return direct + children

    def action_open_direct_history_lines(self):
        """HM2: mở danh sách dòng bút toán trỏ thẳng vào nút tổng hợp."""
        self.ensure_one()
        lines = self._direct_history_lines()
        return {
            'type': 'ir.actions.act_window',
            'name': _(
                'Bút toán lịch sử trực tiếp — %(code)s (%(n)s dòng, %(amt)s)',
                code=self.code,
                n=len(lines),
                amt=self.direct_history_amount,
            ),
            'res_model': 'vas.move.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', lines.ids)],
            'context': {'create': False, 'edit': False},
        }

    def _xml_seed_items(self):
        """Seed module ``connecta_vas`` — nhận diện qua ``ir.model.data``."""
        if not self:
            return self.browse()
        self.env.cr.execute(
            """
            SELECT res_id FROM ir_model_data
             WHERE module = 'connecta_vas'
               AND model = 'vas.cost.item'
               AND res_id = ANY(%s)
            """,
            [list(self.ids)],
        )
        seed_ids = {row[0] for row in self.env.cr.fetchall()}
        return self.filtered(lambda r: r.id in seed_ids)

    def _is_cpd_seed(self):
        self.ensure_one()
        return bool(
            self.code == 'CPD'
            and (self.is_system or self in self._xml_seed_items())
        )

    @api.constrains('parent_id')
    def _check_category_recursion(self):
        if self._has_cycle():
            raise ValidationError(_(
                'Không được tạo vòng lặp cha–con trên khoản mục chi phí.'
            ))

    def _assert_no_parent_cycle(self, new_parent_id):
        """Chặn vòng lặp TRƯỚC parent_store (tránh lỗi Anh «Recursion Detected»)."""
        if not new_parent_id:
            return
        for item in self:
            if new_parent_id == item.id:
                raise ValidationError(_(
                    'Không được tạo vòng lặp cha–con trên khoản mục chi phí.'
                ))
            if item.id and self.search_count([
                ('id', '=', new_parent_id),
                ('id', 'child_of', item.id),
            ]):
                raise ValidationError(_(
                    'Không được tạo vòng lặp cha–con trên khoản mục chi phí.'
                ))

    @api.constrains('factor_group', 'child_ids', 'code')
    def _check_factor_group_on_leaf(self):
        for item in self:
            if item.child_ids:
                continue
            if not item.factor_group:
                raise ValidationError(_(
                    'Nhóm yếu tố bắt buộc trên khoản mục lá «%(code)s — %(name)s». '
                    'Nút tổng hợp (có con) thì để trống được.',
                    code=item.code or '',
                    name=item.name or '',
                ))

    @api.constrains('parent_id', 'code', 'is_system')
    def _check_cpd_no_parent(self):
        for item in self:
            if item._is_cpd_seed() and item.parent_id:
                raise ValidationError(_(
                    'Khoản mục «Chưa phân loại» (CPD) không được có khoản mục cha.'
                ))
            if item.parent_id and item.parent_id._is_cpd_seed():
                raise ValidationError(_(
                    'Khoản mục «Chưa phân loại» (CPD) không được có khoản mục con.'
                ))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_factor_group_on_leaf()
        return records

    def write(self, vals):
        if 'parent_id' in vals:
            parent_id = vals.get('parent_id') or False
            if parent_id and isinstance(parent_id, models.BaseModel):
                parent_id = parent_id.id
            self._assert_no_parent_cycle(parent_id)
        seed = self._xml_seed_items()
        if seed and 'is_system' in vals and not vals.get('is_system'):
            raise UserError(_(
                'Không được bỏ nhãn hệ thống của khoản mục chi phí do module cài đặt. '
                'Chỉ được đổi tên, diễn giải hoặc trạng thái đang dùng.'
            ))
        protected = self.filtered('is_system') | seed
        if protected:
            hit = sorted(self._SEED_STRUCTURAL_FIELDS.intersection(vals))
            if hit:
                for field in hit:
                    new_val = vals[field]
                    for item in protected:
                        old = item[field]
                        old_cmp = old.id if hasattr(old, 'id') else old
                        new_cmp = new_val
                        if field in ('parent_id', 'account_id', 'company_id'):
                            old_cmp = old.id if old else False
                            new_cmp = (
                                new_val.id if hasattr(new_val, 'id')
                                else (new_val or False)
                            )
                        if new_cmp != old_cmp:
                            raise UserError(_(
                                'Không được đổi field cấu trúc (%(fields)s) của khoản mục '
                                'chi phí hệ thống. Chỉ được đổi tên, diễn giải hoặc '
                                'trạng thái đang dùng.',
                                fields=', '.join(hit),
                            ))
        return super().write(vals)

    def _unlink_usage_messages(self):
        """Trả list chuỗi tiếng Việt mô tả chỗ đang dùng (để chặn unlink)."""
        messages = []
        Line = self.env['vas.move.line']
        PayrollMap = self.env['vas.payroll.department.map']
        AccountMap = self.env['vas.account.map']
        Asset = self.env['vas.asset']
        for item in self:
            parts = []
            children = self.search([('parent_id', '=', item.id)])
            if children:
                parts.append(_(
                    '%(n)s khoản mục con (%(codes)s)',
                    n=len(children),
                    codes=', '.join(children.mapped('code')),
                ))
            line_n = Line.search_count([('cost_item_id', '=', item.id)])
            if line_n:
                parts.append(_('%(n)s dòng bút toán', n=line_n))
            pay_n = PayrollMap.search_count([('cost_item_id', '=', item.id)])
            if pay_n:
                parts.append(_('%(n)s dòng map bộ phận lương', n=pay_n))
            map_n = AccountMap.search_count([('cost_item_id', '=', item.id)])
            if map_n:
                parts.append(_('%(n)s dòng ánh xạ tài khoản', n=map_n))
            asset_n = Asset.search_count([('cost_item_id', '=', item.id)])
            if asset_n:
                parts.append(_('%(n)s thẻ tài sản', n=asset_n))
            if parts:
                messages.append(_(
                    'Không xóa được khoản mục %(code)s — %(name)s.\n'
                    'Đang được dùng bởi: %(usage)s.\n'
                    'Việc cần làm: chuyển hoặc xóa các bản ghi đang dùng, '
                    'hoặc ngừng dùng thay vì xóa.',
                    code=item.code,
                    name=item.name,
                    usage='; '.join(parts),
                ))
        return messages

    def unlink(self):
        seed = self._xml_seed_items()
        protected = self.filtered('is_system') | seed
        if protected:
            raise UserError(_(
                'Không được xóa khoản mục chi phí hệ thống (seed module). '
                'Chỉ được đổi tên, diễn giải hoặc trạng thái đang dùng.'
            ))
        for msg in self._unlink_usage_messages():
            raise UserError(msg)
        return super().unlink()

    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        default.setdefault('is_system', False)
        default.setdefault('code', _('%s (sao)', self.code))
        return super().copy(default)
