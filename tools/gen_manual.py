# -*- coding: utf-8 -*-
"""生成系统操作手册 PDF（static/manual.pdf）。

用法: python tools/gen_manual.py
依赖: reportlab（使用内置 STSong-Light CID 字体渲染中文，无需额外字体文件）。
修改手册内容后重新运行本脚本即可更新 PDF。
"""
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, PageBreak)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BASE_DIR, "static", "manual.pdf")

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

PRIMARY = HexColor("#1d4ed8")
MUTED = HexColor("#475569")

S_TITLE = ParagraphStyle("title", fontName="STSong-Light", fontSize=22, leading=30,
                         textColor=PRIMARY, spaceAfter=4, alignment=1)
S_SUB = ParagraphStyle("sub", fontName="STSong-Light", fontSize=11, leading=16,
                       textColor=MUTED, alignment=1, spaceAfter=18)
S_H1 = ParagraphStyle("h1", fontName="STSong-Light", fontSize=15, leading=22,
                      textColor=PRIMARY, spaceBefore=14, spaceAfter=6)
S_H2 = ParagraphStyle("h2", fontName="STSong-Light", fontSize=12.5, leading=18,
                      textColor=HexColor("#0f172a"), spaceBefore=8, spaceAfter=4)
S_P = ParagraphStyle("p", fontName="STSong-Light", fontSize=10.5, leading=17,
                     textColor=HexColor("#0f172a"), spaceAfter=3)
S_LI = ParagraphStyle("li", parent=S_P, leftIndent=14, bulletIndent=4)

story = []
P = lambda t, s=S_P: story.append(Paragraph(t, s))
LI = lambda t: story.append(Paragraph(f"• {t}", S_LI))
SP = lambda h=4: story.append(Spacer(1, h))


def table(headers, rows, widths=None):
    data = [[Paragraph(h, S_P) for h in headers]] + \
           [[Paragraph(str(c), S_P) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#dbeafe")),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    SP(6)


# ============================================================ 封面/概述
P("校招候选人管理系统", S_TITLE)
P("操作手册 · Operation Manual", S_SUB)

P("一、系统概述", S_H1)
P("本系统用于校园招聘候选人的全流程跟踪管理，覆盖 Offer 发放、签约、体检、入职预约到正式入职的各个环节，"
  "支持 Excel 批量导入/导出、简历管理与在线预览、数据透视图表、多级权限分组以及全程操作留痕。"
  "系统跨平台运行（Windows / SUSE Linux），浏览器访问地址默认为 http://服务器IP:8000。")

P("二、登录与角色权限", S_H1)
P("使用管理员分配的账号登录。新建账号默认密码为 123456，首次登录后请联系管理员修改。", S_P)
table(["角色", "候选人数据权限", "其他权限"],
      [["系统管理员", "所有分组：新增 / 编辑 / 删除 / 查看", "全局总览、数据图表、用户与分组管理、全局及各分组字段配置"],
       ["组管理员", "本组：新增 / 编辑 / 删除 / 查看", "本组数据图表、添加本组成员（组成员/只读）、本组字段显示配置"],
       ["组成员", "本组：新增 / 编辑 / 查看（无删除权限）", "—"],
       ["只读", "本组：仅查看", "—"]],
      widths=[70, 190, 220])

P("三、候选人管理", S_H1)
P("3.1 浏览与筛选", S_H2)
LI("列表默认每页 15 条，可在表格下方切换每页条数（15/30/50/100/全部）并翻页。")
LI("顶部搜索框支持全局模糊搜索（姓名、电话、部门等任意字段）。")
LI("表头下方第二行是逐列筛选：文本列输入即模糊匹配，状态列下拉精确匹配，多列条件可同时生效（AND 组合）。")
LI("日期列（毕业时间、预计入职时间等）点击表头可升序/降序排序，空值始终排在最后。")
LI("列宽可拖拽调整：将鼠标移到表头右边缘，出现拖拽手柄后按住左右拖动。")
LI("整张表格的宽度也可自定义：拖动表格容器右下角的拉伸手柄即可整体加宽或收窄。")
LI("过长内容自动省略号截断（默认 320px，可在配置中调整），鼠标悬浮可查看完整内容。")
P("3.2 新增与编辑", S_H2)
LI("「+ 新增候选人」按钮打开表单，带 * 的为必填项；新增时「当前进展」自动带上今天的日期前缀（如 0612：）。")
LI("点击行内「编辑」按钮可修改任意字段；每次保存会自动记录修改日志（谁、何时、把什么从 A 改为 B）。")
LI("「当前进展」列有独立的「更新」按钮：自动在原内容后追加一行今天的日期前缀，便于持续记录跟进情况。")
LI("删除候选人仅系统管理员和组管理员可操作，删除前需二次确认。")
P("3.3 Excel 导入", S_H2)
LI("先点「下载导入模板」获得与当前字段配置完全匹配的表头模板（第一行为表头）。")
LI("点「Excel 导入」选择目标分组并上传 .xlsx 文件；表头按字段配置自动匹配，模板外的列会被忽略，缺失的列不导入。")
LI("已存在的候选人（电话或姓名相同）自动更新，其余新增；导入结果（新增/更新/跳过数量）写入操作日志。")
P("3.4 导出", S_H2)
LI("勾选行首复选框（表头复选框 = 全选当前筛选结果）。")
LI("「导出选中Excel」：将选中候选人按当前字段配置导出为 .xlsx 文件。")
LI("「导出选中简历」：将选中候选人已上传的简历打包为 zip 下载，文件按「姓名_原文件名」命名。")

P("四、简历管理", S_H1)
LI("每位候选人可上传一份简历，支持 .pdf 与 .docx 格式，重复上传自动替换（更换）。")
LI("「预览」：PDF 在浏览器内直接阅读；DOCX 自动转换为网页排版在线查看。")
LI("「下载」获取原始文件；「删除」仅管理员/组管理员可操作。")
LI("所有简历操作（上传/更换/删除）均记录到操作日志。")

P("五、数据图表（系统管理员、组管理员）", S_H1)
LI("分组范围：管理员可选全部分组或指定分组；组管理员固定为本组。")
LI("维度（横轴）：任意可见列或权限分组；选择日期列时可再选日期粒度——按年月日 / 按年月 / 按月份（跨年聚合）。")
LI("系列（图例）：可叠加一个状态列做交叉分析，如「入职三层 × 签约状态」。")
LI("图表类型：柱状图、堆叠柱状图、条形图、环形图、饼图；右侧同步呈现数据透视表（含行列合计）。")

P("六、全局总览（系统管理员）", S_H1)
P("一个页面查看所有分组的候选人与统计（总数/已签约/已入职/高风险），每位候选人附带「最新进展」"
  "（最近一次操作记录），便于快速掌握各组当前状态。")

P("七、操作日志", S_H1)
P("所有新增、修改、删除、导入、导出操作均自动记录，以简洁语言呈现，例如："
  "「招聘专员-小王 修改了「张三」：签约状态：未签约 → 已签约」。管理员可见全部日志，其他角色仅见本组日志。")

P("八、系统管理", S_H1)
P("8.1 系统管理员", S_H2)
LI("权限分组：创建/删除分组（分组下有候选人时不可删除）。")
LI("用户管理：创建/编辑/删除用户，分配角色与分组；新建用户默认密码 123456。")
LI("字段显示配置：「配置范围」选择全局默认或某个分组，勾选要显示的列后保存。")
LI("数据备份与恢复：系统每小时自动备份一次数据库（保留 3 天）；可随时「立即备份」，"
   "也可在备份列表中一键恢复到任意时间点（恢复前系统会自动保存当前状态，误操作可再恢复回来）。")
P("8.2 组管理员（成员管理页）", S_H2)
LI("添加本组成员：只能添加「组成员」或「只读」账号，默认密码 123456。")
LI("本组字段显示配置：勾选本组成员页面上要显示的列，仅影响本组。")

P("九、常见问题", S_H1)
table(["问题", "处理方式"],
      [["登录提示密码错误", "确认大小写；新账号默认密码 123456；忘记密码请联系管理员重置"],
       ["页面提示「登录已失效」", "会话过期，重新登录即可"],
       ["导入失败/数据没进来", "确认文件为 .xlsx 格式、第一行为表头、表头与模板一致；「候选人」列为必填"],
       ["简历上传失败", "仅支持 .pdf / .docx，且不超过配置的大小上限（默认 16MB）"],
       ["想显示/隐藏某些列", "联系系统管理员（全局/各分组）或本组组管理员（本组）调整字段显示配置"],
       ["无法删除候选人", "组成员与只读角色无删除权限，请联系组管理员或系统管理员"]],
      widths=[150, 330])

SP(16)
P("—— 完 ——", S_SUB)

doc = SimpleDocTemplate(OUT_PATH, pagesize=A4,
                        leftMargin=18 * mm, rightMargin=18 * mm,
                        topMargin=16 * mm, bottomMargin=16 * mm,
                        title="校招候选人管理系统操作手册")
doc.build(story)
print(f"操作手册已生成: {OUT_PATH}")
