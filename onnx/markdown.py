import sys
import html

sys.dont_write_bytecode = True

class Markdown:
    def _tableSpanWrite(self, rowList):
        lineList = ["<table>"]

        for a in range(len(rowList)):
            cellList = []

            for b in range(len(rowList[a])):
                cellObject = rowList[a][b]

                if cellObject["isOrigin"] == False:
                    continue

                span = (f' colspan="{cellObject["columnSpan"]}"' if cellObject["columnSpan"] > 1 else "") + (f' rowspan="{cellObject["rowSpan"]}"' if cellObject["rowSpan"] > 1 else "")

                cellList.append(f"<td{span}>{html.escape(cellObject['text'], False)}</td>")

            lineList.append(f"<tr>{''.join(cellList)}</tr>")

        lineList.append("</table>")

        return "\n".join(lineList)

    def _tableWrite(self, rowList):
        isSpan = len([cellObject for rowObject in rowList for cellObject in rowObject if cellObject["columnSpan"] > 1 or cellObject["rowSpan"] > 1]) > 0

        if isSpan:
            return self._tableSpanWrite(rowList)

        lineList = []

        for a in range(len(rowList)):
            textList = [cellObject["text"].replace("|", "\\|") for cellObject in rowList[a]]

            lineList.append(f"| {' | '.join(textList)} |")

            if a == 0:
                lineList.append(f"| {' | '.join('---' for text in textList)} |")

        return "\n".join(lineList)

    def execute(self, itemList):
        resultList = []

        for a in range(len(itemList)):
            if itemList[a]["kind"] == "title":
                resultList.append(f"{'#' * itemList[a]['level']} {itemList[a]['text']}")
            elif itemList[a]["kind"] == "table":
                resultList.append(self._tableWrite(itemList[a]["rowList"]))
            else:
                resultList.append(itemList[a]["text"])

        return "\n\n".join(resultList) + "\n"
