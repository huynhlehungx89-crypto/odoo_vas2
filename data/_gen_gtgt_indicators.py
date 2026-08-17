# -*- coding: utf-8 -*-
"""Sinh seed chỉ tiêu 01/GTGT TT80 + TT89 (công thức là dữ liệu)."""
# Chạy một lần khi cần tái tạo XML — kết quả đã ghi vào vas_gtgt_indicator_seed.xml
# Giữ file này để đối chiếu, không load vào manifest.

TT89 = [
    # code, name, seq, column, source, tag, formula
    ('21', 'Không PS mua bán trong kỳ', 210, 'flag', 'auto_flag', '', ''),
    ('22', 'Thuế GTGT còn được khấu trừ kỳ trước chuyển sang', 220, 'tax', 'carry_forward', '', ''),
    ('23', 'Giá trị HHĐV mua vào', 230, 'value', 'ledger_input_base', '', ''),
    ('23a', 'Trong đó: hàng hóa nhập khẩu (giá trị)', 231, 'value', 'ledger_input_import_base', '', ''),
    ('24', 'Thuế GTGT HHĐV mua vào', 240, 'tax', 'ledger_input_tax', '', ''),
    ('24a', 'Trong đó: hàng hóa nhập khẩu (thuế)', 241, 'tax', 'ledger_input_import_tax', '', ''),
    ('25', 'Thuế GTGT mua vào được khấu trừ kỳ này', 250, 'tax', 'ledger_input_deductible', '', ''),
    ('26', 'HHĐV bán ra không chịu thuế GTGT', 260, 'value', 'ledger_output_value', '26', ''),
    ('29', 'HHĐV bán ra chịu thuế suất 0%', 290, 'value', 'ledger_output_value', '29', ''),
    ('30', 'HHĐV bán ra chịu thuế suất 5%', 300, 'value', 'ledger_output_value', '30', ''),
    ('31', 'Thuế GTGT 5%', 310, 'tax', 'ledger_output_tax', '31', ''),
    ('32', 'HHĐV bán ra chịu thuế suất 10%', 320, 'value', 'ledger_output_value', '32', ''),
    ('32a', 'HHĐV bán ra không kê khai, tính nộp thuế', 321, 'value', 'ledger_output_value', '32a', ''),
    ('32b', 'HHĐV bán ra không tính vào giá tính thuế GTGT', 322, 'value', 'ledger_output_value', '32b', ''),
    ('33', 'Thuế GTGT 10%', 330, 'tax', 'ledger_output_tax', '33', ''),
    ('34a', 'HHĐV bán ra không thuộc phạm vi PL thuế GTGT', 340, 'value', 'ledger_output_value', '34a', ''),
    ('27', 'HHĐV bán ra chịu thuế GTGT (giá trị)', 350, 'value', 'formula', '', '[29]+[30]+[32]+[32a]-[32b]'),
    ('28', 'HHĐV bán ra chịu thuế GTGT (thuế)', 360, 'tax', 'formula', '', '[31]+[33]'),
    ('34', 'Tổng doanh thu HHĐV bán ra', 370, 'value', 'formula', '', '[26]+[27]+[34a]'),
    ('35', 'Tổng thuế GTGT HHĐV bán ra', 380, 'tax', 'formula', '', '[28]'),
    ('36', 'Thuế GTGT phát sinh trong kỳ', 390, 'tax', 'formula', '', '[35]-[25]'),
    ('37', 'Điều chỉnh giảm thuế còn được khấu trừ kỳ trước', 400, 'tax', 'manual', '', ''),
    ('38', 'Điều chỉnh tăng thuế còn được khấu trừ kỳ trước', 410, 'tax', 'manual', '', ''),
    ('39a', 'Thuế GTGT nhận bàn giao được khấu trừ trong kỳ', 420, 'tax', 'manual', '', ''),
    ('40a', 'Thuế GTGT phải nộp HĐ SXKD trong kỳ', 430, 'tax', 'formula', '', '[36]-[22]+[37]-[38]-[39a];max0'),
    ('40b', 'Thuế GTGT ĐAĐT bù trừ với phải nộp SXKD', 440, 'tax', 'manual', '', ''),
    ('40', 'Thuế GTGT còn phải nộp trong kỳ', 450, 'tax', 'formula', '', '[40a]-[40b]'),
    ('41', 'Thuế GTGT chưa khấu trừ hết kỳ này', 460, 'tax', 'formula', '', '[36]-[22]+[37]-[38]-[39a];neg_as_positive'),
    ('42', 'Thuế GTGT đề nghị hoàn', 470, 'tax', 'manual', '', ''),
    ('43', 'Thuế GTGT còn được khấu trừ chuyển kỳ sau', 480, 'tax', 'formula', '', '[41]-[42]'),
]

TT80 = [
    ('21', 'Không PS mua bán trong kỳ', 210, 'flag', 'auto_flag', '', ''),
    ('22', 'Thuế GTGT còn được khấu trừ kỳ trước chuyển sang', 220, 'tax', 'carry_forward', '', ''),
    ('23', 'Giá trị HHĐV mua vào', 230, 'value', 'ledger_input_base', '', ''),
    ('23a', 'Trong đó: hàng hóa nhập khẩu (giá trị)', 231, 'value', 'ledger_input_import_base', '', ''),
    ('24', 'Thuế GTGT HHĐV mua vào', 240, 'tax', 'ledger_input_tax', '', ''),
    ('24a', 'Trong đó: hàng hóa nhập khẩu (thuế)', 241, 'tax', 'ledger_input_import_tax', '', ''),
    ('25', 'Thuế GTGT mua vào được khấu trừ kỳ này', 250, 'tax', 'ledger_input_deductible', '', ''),
    ('26', 'HHĐV bán ra không chịu thuế GTGT', 260, 'value', 'ledger_output_value', '26', ''),
    ('29', 'HHĐV bán ra chịu thuế suất 0%', 290, 'value', 'ledger_output_value', '29', ''),
    ('30', 'HHĐV bán ra chịu thuế suất 5%', 300, 'value', 'ledger_output_value', '30', ''),
    ('31', 'Thuế GTGT 5%', 310, 'tax', 'ledger_output_tax', '31', ''),
    ('32', 'HHĐV bán ra chịu thuế suất 10%', 320, 'value', 'ledger_output_value', '32', ''),
    ('32a', 'HHĐV bán ra không kê khai, tính nộp thuế', 321, 'value', 'ledger_output_value', '32a', ''),
    ('33', 'Thuế GTGT 10%', 330, 'tax', 'ledger_output_tax', '33', ''),
    ('27', 'HHĐV bán ra chịu thuế GTGT (giá trị)', 350, 'value', 'formula', '', '[29]+[30]+[32]+[32a]'),
    ('28', 'HHĐV bán ra chịu thuế GTGT (thuế)', 360, 'tax', 'formula', '', '[31]+[33]'),
    ('34', 'Tổng doanh thu HHĐV bán ra', 370, 'value', 'formula', '', '[26]+[27]'),
    ('35', 'Tổng thuế GTGT HHĐV bán ra', 380, 'tax', 'formula', '', '[28]'),
    ('36', 'Thuế GTGT phát sinh trong kỳ', 390, 'tax', 'formula', '', '[35]-[25]'),
    ('37', 'Điều chỉnh giảm thuế còn được khấu trừ kỳ trước', 400, 'tax', 'manual', '', ''),
    ('38', 'Điều chỉnh tăng thuế còn được khấu trừ kỳ trước', 410, 'tax', 'manual', '', ''),
    ('39a', 'Thuế GTGT nhận bàn giao được khấu trừ trong kỳ', 420, 'tax', 'manual', '', ''),
    ('40a', 'Thuế GTGT phải nộp HĐ SXKD trong kỳ', 430, 'tax', 'formula', '', '[36]-[22]+[37]-[38]-[39a];max0'),
    ('40b', 'Thuế GTGT ĐAĐT bù trừ với phải nộp SXKD', 440, 'tax', 'manual', '', ''),
    ('40', 'Thuế GTGT còn phải nộp trong kỳ', 450, 'tax', 'formula', '', '[40a]-[40b]'),
    ('41', 'Thuế GTGT chưa khấu trừ hết kỳ này', 460, 'tax', 'formula', '', '[36]-[22]+[37]-[38]-[39a];neg_as_positive'),
    ('42', 'Thuế GTGT đề nghị hoàn', 470, 'tax', 'manual', '', ''),
    ('43', 'Thuế GTGT còn được khấu trừ chuyển kỳ sau', 480, 'tax', 'formula', '', '[41]-[42]'),
]


def emit(version_xmlid, rows, prefix):
    out = []
    for code, name, seq, col, src, tag, formula in rows:
        xid = '%s_%s' % (prefix, code.replace('.', '_'))
        out.append(f'''    <record id="{xid}" model="vas.gtgt.indicator">
        <field name="form_version_id" ref="{version_xmlid}"/>
        <field name="code">{code}</field>
        <field name="name">{name}</field>
        <field name="sequence">{seq}</field>
        <field name="column_kind">{col}</field>
        <field name="source_kind">{src}</field>
        <field name="ledger_tag">{tag}</field>
        <field name="formula">{formula}</field>
    </record>''')
    return '\n'.join(out)


if __name__ == '__main__':
    print(emit('vas_gtgt_version_tt89', TT89, 'ind_tt89'))
    print(emit('vas_gtgt_version_tt80', TT80, 'ind_tt80'))
