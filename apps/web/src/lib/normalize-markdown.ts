/**
 * Markdown 预处理：把单行压缩的 GFM 表格展开为多行格式。
 *
 * AI 有时会在一行内输出整张表格，例如：
 *   | 名称 | 用途 | |---|---| | A | 说明 | | B | 说明 |
 * react-markdown 无法识别这种格式，需先拆分为正规多行表格。
 */

const TABLE_LINE_RE = /^\|.+\|$/;
const INLINE_SEP_RE = /\|\s*-{3,}[\s\-:|]*\|/;
const STANDALONE_SEP_RE = /^\|[\s\-:]+\|[\s\-:|]*$/;

export function normalizeInlineTables(md: string): string {
  const lines = md.split('\n');
  const result: string[] = [];

  for (const line of lines) {
    const stripped = line.trim();

    // 非表格行 → 原样保留
    if (!TABLE_LINE_RE.test(stripped)) {
      result.push(line);
      continue;
    }

    // 整行就是个分隔行 → 正常多行表格
    if (STANDALONE_SEP_RE.test(stripped)) {
      result.push(line);
      continue;
    }

    // 寻找行内分隔符（如 |---|---|）
    const sepMatch = INLINE_SEP_RE.exec(stripped);
    if (!sepMatch) {
      result.push(line);
      continue;
    }

    // 分隔符后无内容 → 不是压缩表格
    const sepEnd = sepMatch.index + sepMatch[0].length;
    if (!stripped.slice(sepEnd).trim()) {
      result.push(line);
      continue;
    }

    const headerPart = stripped.slice(0, sepMatch.index).trimEnd();
    const bodyPart = stripped.slice(sepEnd).trimStart();
    const sepText = sepMatch[0];

    // 列数 = header 中 | 的数量 - 1
    const colCount = (headerPart.match(/\|/g) || []).length - 1;
    if (colCount < 1) {
      result.push(line);
      continue;
    }

    result.push(headerPart);
    result.push(sepText);

    // 按 | 拆分 body，按列数分组为行
    const bodyCells = bodyPart.split('|').map((c) => c.trim()).filter(Boolean);
    for (let i = 0; i < bodyCells.length; i += colCount) {
      const rowCells = bodyCells.slice(i, i + colCount);
      if (rowCells.length > 0) {
        result.push('| ' + rowCells.join(' | ') + ' |');
      }
    }
  }

  return result.join('\n');
}
