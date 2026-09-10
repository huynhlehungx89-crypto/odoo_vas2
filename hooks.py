# -*- coding: utf-8 -*-
"""Hooks cài/nâng cấp — không gắn vào ORM lifecycle thường."""
import logging

from odoo.tools import config

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    _reparent_vn_operations_menu(env)
    try:
        env['vas.variance.account.config']._seed_defaults_tt133()
    except Exception:  # noqa: BLE001 — seed không chặn cài module
        _logger.exception('connecta_vas: seed TK xử lý vượt định mức thất bại')
    _ensure_account_113(env)
    _ensure_at_install_account_env(env)


def _ensure_account_113(env):
    """Noupdate CoA: bổ sung TK 113 khi nâng cấp DB cũ + cập nhật B01a mã 110."""
    regime = env.ref('connecta_vas.vas_regime_tt133', raise_if_not_found=False)
    if not regime:
        return
    Account = env['vas.account']
    if not Account.search([('code', '=', '113'), ('regime_id', '=', regime.id)], limit=1):
        Account.create({
            'code': '113',
            'name': 'Tiền đang chuyển',
            'regime_id': regime.id,
            'ending_balance_policy': 'debit',
            'account_type': 'asset',
            'reconcile': False,
            'active': True,
        })
        _logger.info('connecta_vas: đã tạo TK 113 Tiền đang chuyển')
    line = env.ref('connecta_vas.vas_report_line_b01a_110', raise_if_not_found=False)
    if line and line.account_codes and '113' not in line.account_codes.split(','):
        codes = [c.strip() for c in line.account_codes.split(',') if c.strip()]
        if '113' not in codes:
            # Chèn sau 1122 nếu có
            if '1122' in codes:
                idx = codes.index('1122') + 1
                codes.insert(idx, '113')
            else:
                codes.append('113')
            line.account_codes = ','.join(codes)
            _logger.info('connecta_vas: B01a mã 110 thêm 113')


def _ensure_at_install_account_env(env):
    """Môi trường account Odoo trước at_install tests.

    post_init chạy sau data XML, trước suite at_install. Ca W1–W6 / prepaid /
    W3 tạo ``account.tax`` / ``account.move`` khi chưa có CoA → tax_group_id /
    country_id / account_id rỗng. Không sửa ca cũ; chỉ nạp CoA khi đang chạy
    bộ kiểm. Cài khách hàng (không ``--test-enable``) không đụng.
    """
    if not config.get('test_enable'):
        return
    vn = env.ref('base.vn', raise_if_not_found=False)
    Chart = env['account.chart.template']
    Group = env['account.tax.group']
    Account = env['account.account']
    for company in env['res.company'].search([]):
        if vn and not company.country_id:
            company.country_id = vn
        if vn and not company.account_fiscal_country_id:
            company.account_fiscal_country_id = vn
        if not Account.search([('company_ids', 'in', company.id)], limit=1):
            try:
                Chart.try_loading('generic_coa', company, install_demo=False)
            except Exception:  # noqa: BLE001
                _logger.exception(
                    'connecta_vas: try_loading generic_coa thất bại company=%s',
                    company.id,
                )
        if not Group.search([('company_id', '=', company.id)], limit=1):
            country = company.account_fiscal_country_id or company.country_id
            Group.create({
                'name': 'GTGT',
                'company_id': company.id,
                'country_id': country.id if country else False,
            })


def _reparent_vn_operations_menu(env):
    """Đưa "Nghiệp vụ VN" vào đúng app kế toán đang mở.

    Community: `account.menu_finance` = app Invoicing — parent XML mặc định.
    Enterprise (`accountant`): app đó đổi tên thành Invoicing rỗng; các mục
    Dashboard/Customers/... bị kéo sang `accountant.menu_accounting`
    (= app Accounting). Menu của ta vẫn nằm dưới Invoicing nên người dùng
    mở Accounting không thấy gì. Kéo theo khi app Accounting tồn tại.
    """
    menu = env.ref('connecta_vas.menu_vas_vn_operations', raise_if_not_found=False)
    if not menu:
        return
    accounting = env.ref('accountant.menu_accounting', raise_if_not_found=False)
    if not accounting:
        _logger.info(
            'connecta_vas: khong co accountant.menu_accounting — '
            'giu Nghiệp vụ VN duoi account.menu_finance (Invoicing)',
        )
        return
    if menu.parent_id == accounting:
        return
    _logger.info(
        'connecta_vas: chuyen menu Nghiệp vụ VN tu %s -> %s (Accounting)',
        menu.parent_id.display_name, accounting.display_name,
    )
    menu.parent_id = accounting
