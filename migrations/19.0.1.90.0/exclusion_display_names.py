# -*- coding: utf-8 -*-
"""Tên ngành Phụ lục I NĐ 174 — VSIC / HS. Không dùng cho máy tính thuế."""
from __future__ import annotations

import re

# VSIC 2007/2018 — tên ngành thật (cấp 2 và một phần cấp 3).
VSIC = {
    '06': 'Khai thác dầu thô và khí đốt tự nhiên',
    '07': 'Khai thác quặng kim loại',
    '08': 'Khai khoáng khác',
    '09': 'Hoạt động dịch vụ hỗ trợ khai khoáng',
    '10': 'Sản xuất thực phẩm',
    '11': 'Sản xuất đồ uống',
    '12': 'Sản xuất sản phẩm thuốc lá',
    '13': 'Sản xuất sản phẩm dệt',
    '14': 'Sản xuất trang phục',
    '15': 'Sản xuất da và các sản phẩm có liên quan',
    '16': 'Chế biến gỗ và sản xuất sản phẩm từ gỗ, tre, nứa',
    '17': 'Sản xuất giấy và sản phẩm từ giấy',
    '18': 'In, sao chép bản ghi các loại',
    '19': 'Sản xuất than cốc, sản phẩm dầu mỏ tinh chế',
    '20': 'Sản xuất hóa chất và sản phẩm hóa chất',
    '21': 'Sản xuất thuốc, hóa dược và dược liệu',
    '22': 'Sản xuất sản phẩm từ cao su và plastic',
    '23': 'Sản xuất sản phẩm từ khoáng phi kim loại khác',
    '24': 'Sản xuất kim loại',
    '61': 'Viễn thông',
    '62': 'Lập trình máy vi tính, tư vấn và hoạt động liên quan',
    '63': 'Hoạt động dịch vụ thông tin',
    '64': 'Hoạt động dịch vụ tài chính (trừ bảo hiểm và quỹ hưu trí)',
    '65': 'Bảo hiểm, tái bảo hiểm và quỹ hưu trí',
    '66': 'Hoạt động hỗ trợ dịch vụ tài chính',
    '68': 'Hoạt động kinh doanh bất động sản',
    '061': 'Khai thác dầu thô',
    '062': 'Khai thác khí đốt tự nhiên',
    '071': 'Khai thác quặng sắt',
    '072': 'Khai thác quặng kim loại khác trừ quặng sắt',
    '073': 'Khai thác quặng uranium và quặng thorium',
    '081': 'Khai thác đá, cát, sỏi, đất sét',
    '091': 'Dịch vụ hỗ trợ khai thác dầu thô và khí đốt tự nhiên',
    '099': 'Dịch vụ hỗ trợ khai khoáng khác',
    '101': 'Chế biến và bảo quản thịt',
    '106': 'Sản xuất sản phẩm bột mì và bột khác',
    '120': 'Sản xuất sản phẩm thuốc lá',
    '125': 'Sản xuất sản phẩm thuốc lá',
    '201': 'Sản xuất hóa chất cơ bản',
    '202': 'Sản xuất sản phẩm hóa chất khác',
    '239': 'Sản xuất sản phẩm từ khoáng phi kim loại khác',
    '639': 'Hoạt động dịch vụ thông tin khác',
    '661': 'Hoạt động hỗ trợ dịch vụ tài chính (trừ bảo hiểm)',
    '662': 'Hoạt động hỗ trợ bảo hiểm và quỹ hưu trí',
    '663': 'Hoạt động của quỹ',
    '681': 'Kinh doanh bất động sản',
    '682': 'Tư vấn, môi giới, đấu giá bất động sản',
}

# Mã trùng số hiệu văn bản — OCR nhầm, không phải ngành.
VSIC_UNREADABLE = {'174', '204'}

HS4 = {
    '2507': 'Kaolin và đất sét kaolin khác',
    '2508': 'Đất sét khác, andaluzit, kyanit, silimanit',
    '2509': 'Đá phấn',
    '2510': 'Photphat canxi tự nhiên, photphat nhôm-canxi',
    '2511': 'Barit / witherit',
    '2512': 'Đá bọt, đá mã não, xỉ',
    '2513': 'Đá bọt, emergi, corindon tự nhiên, garnet',
    '2514': 'Đá phiến',
    '2515': 'Đá cẩm thạch, travertin',
    '2516': 'Granit, porphyr, bazan',
    '2517': 'Sỏi, đá cuội, đá dăm; macadam',
    '2518': 'Đá dolomit',
    '2519': 'Magie carbonat tự nhiên (magnesit)',
    '2520': 'Thạch cao, anhydrit, vữa',
    '2521': 'Đá vôi làm vôi hoặc xi măng',
    '2522': 'Vôi sống, vôi tôi, vôi thủy lực',
    '2523': 'Xi măng portland, alumin, xỉ',
    '2601': 'Quặng sắt và tinh quặng sắt',
    '2602': 'Quặng mangan',
    '2603': 'Quặng đồng',
    '2604': 'Quặng niken',
    '2605': 'Quặng coban',
    '2606': 'Quặng nhôm',
    '2607': 'Quặng chì',
    '2608': 'Quặng kẽm',
    '2609': 'Quặng thiếc',
    '2610': 'Quặng crom',
    '2611': 'Quặng vonfram',
    '2612': 'Quặng uranium hoặc thorium',
    '2614': 'Quặng titan',
    '2615': 'Quặng niobi, tantali, vanadi hoặc zirconi',
    '2616': 'Quặng kim loại quý và tinh quặng',
    '2617': 'Quặng và tinh quặng khác',
    '2709': 'Dầu thô từ khoáng bitum',
    '2710': 'Dầu mỏ và dầu thu được từ khoáng bitum, trừ dầu thô',
    '2711': 'Khí dầu mỏ và hydrocarbon khí khác',
    '2712': 'Vazơlin, parafin, sáp khoáng',
    '2713': 'Cốc dầu mỏ, bitum dầu mỏ và sản phẩm dư dầu mỏ',
    '2714': 'Bitum và asphan tự nhiên; đá bitum',
    '2715': 'Hỗn hợp bitum từ asphan, nhựa dầu mỏ',
}


def vsic_name(code: str) -> str:
    code = (code or '').strip()
    if code in VSIC_UNREADABLE:
        return 'Chưa xác định — mã %s (Phụ lục I NĐ 174)' % code
    if code in VSIC:
        return VSIC[code]
    for n in (6, 5, 4, 3, 2):
        if len(code) > n and code[:n] in VSIC:
            return '%s (mã %s)' % (VSIC[code[:n]], code)
    return 'Chưa xác định — mã VSIC %s (Phụ lục I NĐ 174)' % code


def hs_name(code: str) -> str:
    code = (code or '').strip()
    key = code.replace('.', '')[:4]
    if key in HS4:
        return 'Hàng nhập khẩu — %s (HS %s)' % (HS4[key], code)
    return 'Chưa xác định — mã HS %s (Phụ lục I NĐ 174)' % code


def display_name(code: str, kind: str, old: str) -> str:
    if kind == 'vsic':
        if old and 'OCR' not in old and not old.startswith('PL I'):
            return old
        return vsic_name(code)
    if kind == 'hs':
        if old and 'mã HS' not in old and 'OCR' not in old:
            return old
        return hs_name(code)
    return old


def patch_xml(path: str) -> tuple[int, int]:
    text = open(path, encoding='utf-8').read()
    rec_re = re.compile(
        r'(<record id="[^"]+" model="vas.gtgt.reduction.exclusion">.*?'
        r'<field name="code">([^<]+)</field>.*?'
        r'<field name="name">)([^<]+)(</field>.*?'
        r'<field name="code_kind">([^<]+)</field>)',
        re.S,
    )
    n_ocr = n_und = 0

    def repl(m):
        nonlocal n_ocr, n_und
        prefix, code, old, suffix, kind = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        new = display_name(code, kind, old)
        if new != old:
            n_ocr += 1
        if new.startswith('Chưa xác định'):
            n_und += 1
        return prefix + new + suffix

    new_text = rec_re.sub(repl, text)
    open(path, 'w', encoding='utf-8', newline='\n').write(new_text)
    return n_ocr, n_und
