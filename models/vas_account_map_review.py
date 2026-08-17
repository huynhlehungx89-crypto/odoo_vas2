# -*- coding: utf-8 -*-
from odoo import _, api, fields, models, tools


class VasAccountMapReview(models.Model):
    """Rà soát nhóm sản phẩm chưa khai ánh xạ tài khoản.

    QUÉT NGƯỢC — bắt buộc: nguồn là `product.category` CÓ sản phẩm, rồi mới LEFT JOIN
    sang `vas.account.map`. Nếu đọc xuôi từ bảng ánh xạ thì nhóm chưa khai không có
    dòng nào nên sẽ không bao giờ hiện ra, đúng cái cần phát hiện lại bị bỏ sót.
    """

    _name = 'vas.account.map.review'
    _description = 'Rà soát ánh xạ tài khoản theo nhóm sản phẩm'
    _auto = False
    _order = 'state desc, product_count desc, id'

    category_id = fields.Many2one('product.category', string='Nhóm sản phẩm', readonly=True)
    company_id = fields.Many2one('res.company', string='Công ty', readonly=True)
    regime_id = fields.Many2one('vas.regime', string='Chế độ kế toán', readonly=True)
    product_count = fields.Integer(string='Số sản phẩm', readonly=True)
    map_id = fields.Many2one('vas.account.map', string='Dòng ánh xạ', readonly=True)
    stock_account_id = fields.Many2one('vas.account', string='TK tồn kho', readonly=True)
    revenue_account_id = fields.Many2one('vas.account', string='TK doanh thu', readonly=True)
    cogs_account_id = fields.Many2one('vas.account', string='TK giá vốn', readonly=True)
    expense_account_id = fields.Many2one('vas.account', string='TK chi phí', readonly=True)
    state = fields.Selection(
        selection=[
            ('missing', 'CHƯA KHAI'),
            ('partial', 'KHAI THIẾU'),
            ('ok', 'Đã khai'),
        ],
        string='Trạng thái',
        readonly=True,
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    (pc.id * 100000 + c.id)                     AS id,
                    pc.id                                       AS category_id,
                    c.id                                        AS company_id,
                    c.vas_regime_id                             AS regime_id,
                    cnt.product_count                           AS product_count,
                    COALESCE(ms.id, mg.id)                      AS map_id,
                    COALESCE(ms.stock_account_id, mg.stock_account_id)     AS stock_account_id,
                    COALESCE(ms.revenue_account_id, mg.revenue_account_id) AS revenue_account_id,
                    COALESCE(ms.cogs_account_id, mg.cogs_account_id)       AS cogs_account_id,
                    COALESCE(ms.expense_account_id, mg.expense_account_id) AS expense_account_id,
                    CASE
                        WHEN COALESCE(ms.id, mg.id) IS NULL THEN 'missing'
                        WHEN COALESCE(ms.stock_account_id, mg.stock_account_id) IS NULL
                          OR COALESCE(ms.revenue_account_id, mg.revenue_account_id) IS NULL
                          OR COALESCE(ms.cogs_account_id, mg.cogs_account_id) IS NULL
                        THEN 'partial'
                        ELSE 'ok'
                    END                                         AS state
                FROM product_category pc
                JOIN (
                    SELECT categ_id, COUNT(*) AS product_count
                      FROM product_template
                     WHERE active IS TRUE AND categ_id IS NOT NULL
                     GROUP BY categ_id
                ) cnt ON cnt.categ_id = pc.id
                CROSS JOIN res_company c
                LEFT JOIN vas_account_map ms
                       ON ms.category_id = pc.id
                      AND ms.apply_to = 'category'
                      AND ms.active IS TRUE
                      AND ms.regime_id = c.vas_regime_id
                      AND ms.company_id = c.id
                LEFT JOIN vas_account_map mg
                       ON mg.category_id = pc.id
                      AND mg.apply_to = 'category'
                      AND mg.active IS TRUE
                      AND mg.regime_id = c.vas_regime_id
                      AND mg.company_id IS NULL
                WHERE c.vas_regime_id IS NOT NULL
            )
        """)

    def _search(self, *args, **kwargs):
        # View SQL đọc thẳng bảng nên nằm ngoài mạng phụ thuộc của ORM: Odoo không
        # biết dòng ánh xạ vừa khai làm thay đổi kết quả. Phải tự đẩy cache xuống DB
        # rồi tự vô hiệu cache của view, nếu không id dòng không đổi sẽ trả trạng
        # thái cũ ("CHƯA KHAI" dù vừa khai xong).
        self.env['vas.account.map'].flush_model()
        self.env['product.template'].flush_model()
        self.env['product.category'].flush_model()
        self.invalidate_model()
        return super()._search(*args, **kwargs)

    def action_configure(self):
        """Khai ngay tại màn rà soát: mở dòng ánh xạ sẵn có, hoặc tạo mới đã điền nhóm."""
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Ánh xạ tài khoản — %s', self.category_id.display_name),
            'res_model': 'vas.account.map',
            'view_mode': 'form',
            'target': 'new',
        }
        if self.map_id:
            action['res_id'] = self.map_id.id
        else:
            action['context'] = {
                'default_regime_id': self.regime_id.id,
                'default_company_id': self.company_id.id,
                'default_apply_to': 'category',
                'default_category_id': self.category_id.id,
            }
        return action

    @api.model
    def _missing_summary(self, company):
        """Chuỗi tóm tắt các nhóm thiếu cấu hình, dùng cho thông báo sau Đồng bộ."""
        rows = self.search([
            ('company_id', '=', company.id),
            ('state', 'in', ('missing', 'partial')),
        ])
        return [
            f'{row.category_id.display_name} ({row.product_count} SP, '
            f'{dict(self._fields["state"].selection)[row.state]})'
            for row in rows
        ]
