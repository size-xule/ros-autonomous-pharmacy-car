#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""Durable UTF-8 MD5 journal and atomic XLSX export; Python 2.7/3.6 stdlib only."""
from __future__ import unicode_literals, print_function
import argparse
import base64
import hashlib
import json
import os
import re
import time
import zipfile
from xml.sax.saxutils import escape

TEXT = type(u'')
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'


def digest(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def cell(value):
    value = '' if value is None else (value if isinstance(value, TEXT) else TEXT(value))
    # XML cannot represent control characters; JSON-escape those cells losslessly.
    if re.search('[\x00-\x08\x0b\x0c\x0e-\x1f]', value):
        value = json.dumps(value, ensure_ascii=False)
    return '<c t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % escape(value)


def sheet(rows):
    return ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>' % (
        NS, ''.join('<row r="%d">%s</row>' % (i, ''.join(cell(v) for v in row))
                    for i, row in enumerate(rows, 1)))).encode('utf-8')


def workbook(entries):
    records = [['圈次', '类型', '明文', '明文UTF-8 MD5', '播报文字', '播报UTF-8 MD5',
                '播放状态', '原始字节Base64', '原始字节MD5', '时间戳', '编号']]
    for e in entries:
        records.append([e.get(k, '') for k in ('round', 'kind', 'plain', 'md5', 'speech',
                        'speech_md5', 'status', 'raw_base64', 'raw_md5', 'timestamp', 'id')])
    summary = [['圈次', '口径（待裁判确认）', '拼接明文（顺序不变，LF换行，无末尾换行）', 'UTF-8 MD5']]
    for round_id in sorted(set(e['round'] for e in entries)):
        group = [e for e in entries if e['round'] == round_id]
        for scope, values in (
                ('识别内容：板一已选任务+干扰/错误码+板二',
                 [e['plain'] for e in group if e['kind'] in ('board1_task', 'interference', 'board2')]),
                ('本圈已完成播报：含取样、送样',
                 [e['speech'] for e in group if e.get('status') == 'DONE' and e.get('speech')])):
            plain = '\n'.join(values)
            summary.append([round_id, scope, plain, digest(plain)])
    notes = [['说明', '内容'], ['算法', '标准MD5；中文UTF-8；不含BOM，不反推明文'],
             ['格式', '板一保留实际选择的ABC-1形式；沿用现有样本编码，不声明为官方映射'],
             ['未确认规则', '逐项和两种圈汇总均保留；LF拼接只是本程序的明确约定，不代表官方模板'],
             ['原始码', '原始字节通过Base64保全；非UTF-8错误码明文显示base64:前缀，其原始MD5另列'],
             ['计分', '不自动判分，不自动点击最终验证；由裁判核验'],
             ['播放状态', '只有DONE纳入已完成播报汇总；失败、超时、中断不算完成'],
             ['日志', 'records.jsonl先fsync，再原子替换Excel；每次启动独立目录']]
    names = ['逐项记录', '每圈汇总', '口径说明']
    parts = {'xl/worksheets/sheet%d.xml' % i: sheet(rows)
             for i, rows in enumerate((records, summary, notes), 1)}
    parts['[Content_Types].xml'] = ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
        ''.join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % i for i in range(1, 4)) + '</Types>')
    parts['_rels/.rels'] = '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%s/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (PKG_REL, REL)
    parts['xl/workbook.xml'] = '<workbook xmlns="%s" xmlns:r="%s"><sheets>%s</sheets></workbook>' % (NS, REL,
        ''.join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (n, i, i) for i, n in enumerate(names, 1)))
    parts['xl/_rels/workbook.xml.rels'] = '<Relationships xmlns="%s">%s</Relationships>' % (PKG_REL,
        ''.join('<Relationship Id="rId%d" Type="%s/worksheet" Target="worksheets/sheet%d.xml"/>' % (i, REL, i) for i in range(1, 4)))
    return parts


def convert(source, target):
    entries = []
    if os.path.isfile(source):
        with open(source, 'rb') as stream:
            entries = [json.loads(line.decode('utf-8')) for line in stream if line.strip()]
    temporary = target + '.tmp'
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in workbook(entries).items():
            archive.writestr(name, data.encode('utf-8') if isinstance(data, TEXT) else data)
    with open(temporary, 'rb') as stream:
        os.fsync(stream.fileno())
    os.rename(temporary, target)
    fd = os.open(os.path.dirname(os.path.abspath(target)), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save(directory, entry=None):
    if not os.path.isdir(directory):
        os.makedirs(directory)
    source = os.path.join(directory, 'records.jsonl')
    if entry is not None:
        entry = dict(entry)
        if entry.get('raw_base64') or entry.get('kind') == 'interference':
            raw = base64.b64decode(entry['raw_base64'])
            entry['raw_md5'] = hashlib.md5(raw).hexdigest()
            if entry.get('kind') == 'interference':
                try:
                    entry['plain'] = raw.decode('utf-8')
                except UnicodeDecodeError:
                    entry['plain'] = 'base64:' + entry['raw_base64']
        entry['md5'] = digest(entry.get('plain', ''))
        entry['speech_md5'] = digest(entry.get('speech', '')) if entry.get('speech') else ''
        entry.setdefault('timestamp', time.time())
        entry.setdefault('round', 0)
        with open(source, 'ab') as stream:
            stream.write((json.dumps(entry, ensure_ascii=True) + '\n').encode('ascii'))
            stream.flush()
            os.fsync(stream.fileno())
    convert(source, os.path.join(directory, 'MD5.xlsx'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory')
    parser.add_argument('--entry')
    parser.add_argument('--input')
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.directory:
        save(args.directory, json.loads(args.entry) if args.entry else None)
    elif args.input and args.output:
        convert(args.input, args.output)
    else:
        parser.error('use --directory [--entry JSON] or --input JSONL --output XLSX')


if __name__ == '__main__':
    main()
