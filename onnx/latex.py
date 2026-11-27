import sys
import os
import re
import unicodedata
import cv2
import numpy
from tokenizers import Tokenizer

sys.dont_write_bytecode = True

# Source
from helper import onnxSessionBuild, tensorNormalize, imageInkBuild, characterNormalize, xmlNodeTag, xmlAttributeValue, blockMathList, valueFalseList

class Latex:
    def _commandWrite(self, name, argumentList):
        return f"\\{name}" + "".join(f"{{{argument}}}" for argument in argumentList)

    def _propertyValue(self, node, tag):
        tagNode = xmlNodeTag(node)

        for propertyNode in node:
            if xmlNodeTag(propertyNode) != f"{tagNode}Pr":
                continue

            for valueNode in propertyNode:
                if xmlNodeTag(valueNode) == tag:
                    return xmlAttributeValue(valueNode, ["val"])

        if tagNode in self.defaultObject and tag in self.defaultObject[tagNode]:
            return self.defaultObject[tagNode][tag]

        return None

    def _switchCheck(self, node, tag):
        value = self._propertyValue(node, tag)

        return value is not None and value not in valueFalseList

    def _partList(self, node, tag, isName):
        return ["".join(self._nodeText(partNode, isName) for partNode in childNode).strip() for childNode in node if xmlNodeTag(childNode) == tag]

    def _partText(self, node, tag, isName):
        return "".join(self._partList(node, tag, isName))

    def _groupWrite(self, text):
        return text if len(text) == 1 else f"{{{text}}}"

    def _scriptWrite(self, base, subscript, superscript):
        return base + (f"_{{{subscript}}}" if subscript != "" else "") + (f"^{{{superscript}}}" if superscript != "" else "")

    def _delimiterWrite(self, node, tag):
        character = self._propertyValue(node, tag)

        return "." if character == "" else character.translate(self.escapeObject)

    def _markWrite(self, character, text, isTop):
        nameObject = self.markObject[character] if character in self.markObject else {}

        keyList = ["wide", "narrow"] if len(text) > 1 else ["narrow", "wide"]

        nameList = [nameObject[key] for key in keyList if key in nameObject]

        if len(nameList) > 0:
            return self._commandWrite(nameList[0], [text])

        return self._commandWrite("overset" if isTop else "underset", [character, text])

    def _environmentWrite(self, name, rowList):
        separator = " \\\\ "

        return f"\\begin{{{name}}} {separator.join(rowList)} \\end{{{name}}}"

    def _styleFind(self, character, command):
        if characterNormalize(character, blockMathList) == character:
            return command if command != self.commandUpright or unicodedata.category(character)[0] == "L" else ""

        name = unicodedata.name(character, "")

        nameList = [styleObject["command"] for styleObject in self.styleNameList if styleObject["name"] in name]

        return nameList[0] if len(nameList) > 0 else ""

    def _styleWrite(self, command, text):
        textPlain = characterNormalize(text, blockMathList).translate(self.escapeObject)

        return self._commandWrite(command, [textPlain]) if command != "" and len([character for character in textPlain if character.isalnum()]) > 0 else textPlain

    def _styleText(self, node, text):
        script = self._propertyValue(node, "scr")
        style = self._propertyValue(node, "sty")

        commandRun = self.styleScriptObject[script] if script in self.styleScriptObject else ""

        if commandRun == "" and style in self.styleWeightObject:
            commandRun = self.styleWeightObject[style]

        result = ""

        start = 0

        for a in range(1, len(text) + 1):
            if a < len(text) and text[a].isspace() == text[start].isspace() and self._styleFind(text[a], commandRun) == self._styleFind(text[start], commandRun):
                continue

            result += self._styleWrite(self._styleFind(text[start], commandRun), text[start:a])

            start = a

        return result

    def _nodeText(self, node, isName):
        tag = xmlNodeTag(node)

        if tag == "r":
            textRun = "".join(textNode.text for textNode in node if xmlNodeTag(textNode) == "t" and textNode.text is not None)

            text = characterNormalize(textRun, blockMathList).translate(self.escapeObject)

            if text.strip() != "" and isName:
                return self._commandWrite("operatorname", [text.strip()])

            if text.strip() != "" and self._switchCheck(node, "nor"):
                return self._commandWrite("text", [text])

            return self._styleText(node, textRun)

        if tag == "f":
            typeFraction = self._propertyValue(node, "type")

            numerator = self._partText(node, "num", False)
            denominator = self._partText(node, "den", False)

            if typeFraction in self.fractionLineList:
                return f"{self._groupWrite(numerator)}/{self._groupWrite(denominator)}"

            if typeFraction == "noBar":
                return self._commandWrite("genfrac", ["", "", "0pt", "", numerator, denominator])

            return self._commandWrite("frac", [numerator, denominator])

        if tag in self.scriptList:
            return self._scriptWrite(self._groupWrite(self._partText(node, "e", isName)), self._partText(node, "sub", False), self._partText(node, "sup", False))

        if tag == "sPre":
            return self._scriptWrite("{}", self._partText(node, "sub", False), self._partText(node, "sup", False)) + self._groupWrite(self._partText(node, "e", isName))

        if tag == "nary":
            subscript = "" if self._switchCheck(node, "subHide") else self._partText(node, "sub", False)
            superscript = "" if self._switchCheck(node, "supHide") else self._partText(node, "sup", False)

            return self._scriptWrite(self._propertyValue(node, "chr"), subscript, superscript) + self._groupWrite(self._partText(node, "e", isName))

        if tag == "d":
            separator = f" \\middle{self._delimiterWrite(node, 'sepChr')} "

            return f"\\left{self._delimiterWrite(node, 'begChr')}{separator.join(self._partList(node, 'e', isName))}\\right{self._delimiterWrite(node, 'endChr')}"

        if tag == "func":
            return self._partText(node, "fName", True) + self._groupWrite(self._partText(node, "e", isName))

        if tag in self.limitObject:
            return self._commandWrite(self.limitObject[tag], [self._partText(node, "lim", False), self._partText(node, "e", isName)])

        if tag in self.markList:
            return self._markWrite(self._propertyValue(node, "chr"), self._partText(node, "e", isName), self._propertyValue(node, "pos") == "top")

        if tag == "bar":
            return self._commandWrite("overline" if self._propertyValue(node, "pos") == "top" else "underline", [self._partText(node, "e", isName)])

        if tag == "rad":
            degree = "" if self._switchCheck(node, "degHide") else self._partText(node, "deg", False)

            return self._commandWrite("sqrt" if degree == "" else f"sqrt[{degree}]", [self._partText(node, "e", isName)])

        if tag == "eqArr":
            rowList = self._partList(node, "e", isName)

            if len(rowList) == 1:
                return rowList[0].replace("\\&", "")

            return self._environmentWrite("aligned", [text.replace("\\&", "&") for text in rowList])

        if tag == "m":
            return self._environmentWrite("matrix", [" & ".join(self._partList(rowNode, "e", isName)) for rowNode in node if xmlNodeTag(rowNode) == "mr"])

        if tag == "borderBox":
            return self._commandWrite("boxed", [self._partText(node, "e", isName)])

        if tag == "phant" and self._propertyValue(node, "show") in valueFalseList:
            return self._commandWrite("phantom", [self._partText(node, "e", isName)])

        return "".join(self._nodeText(childNode, isName) for childNode in node)

    def _formulaText(self, node, mark):
        text = " ".join(self._nodeText(node, False).split())

        return f"{mark}{text}{mark}" if text != "" else ""

    def _nodeWrite(self, node, text):
        for childNode in list(node):
            node.remove(childNode)

        node.tag = "t"
        node.text = text

    def _imageCrop(self, bboxList, scale, image, bboxNumberList):
        left = max(0, int(bboxList[0] * scale))
        top = max(0, int(bboxList[1] * scale))

        imageCrop = image[top:int(bboxList[3] * scale), left:int(bboxList[2] * scale)].copy()

        if imageCrop.shape[0] == 0 or imageCrop.shape[1] == 0:
            return imageCrop

        colorList = numpy.median(imageCrop.reshape(-1, 3), axis=0)

        _, labelMap = cv2.connectedComponents(imageInkBuild(imageCrop))

        for a in range(len(bboxNumberList)):
            numberLeft = max(0, int(bboxNumberList[a][0] * scale) - left)
            numberRight = max(0, int(bboxNumberList[a][2] * scale) - left)

            if numberLeft + numberRight > imageCrop.shape[1]:
                numberRight = imageCrop.shape[1]
            else:
                numberLeft = 0

            idList = [labelId for labelId in numpy.unique(labelMap[:, numberLeft:numberRight]) if labelId != 0]

            imageCrop[numpy.isin(labelMap, idList)] = colorList
            imageCrop[:, numberLeft:numberRight] = colorList

        return imageCrop

    def _tensorBuild(self, imageCrop):
        imageGray = cv2.cvtColor(imageCrop, cv2.COLOR_BGR2GRAY).astype(numpy.float32)

        low = float(imageGray.min())
        high = float(imageGray.max())

        if high > low:
            inkLeft, inkTop, inkWidth, inkHeight = cv2.boundingRect(cv2.findNonZero(((imageGray - low) / (high - low) * 255.0 < self.levelInk).astype(numpy.uint8)))

            imageCrop = imageCrop[inkTop:inkTop + inkHeight, inkLeft:inkLeft + inkWidth]

        ratio = self.imageSize / max(imageCrop.shape[0], imageCrop.shape[1])

        width = max(1, int(imageCrop.shape[1] * ratio))
        height = max(1, int(imageCrop.shape[0] * ratio))

        left = (self.imageSize - width) // 2
        top = (self.imageSize - height) // 2

        imagePad = numpy.zeros((self.imageSize, self.imageSize, 3), dtype=numpy.uint8)
        imagePad[top:top + height, left:left + width] = cv2.resize(cv2.cvtColor(imageCrop, cv2.COLOR_BGR2RGB), (width, height), interpolation=cv2.INTER_LINEAR)

        return tensorNormalize(imagePad, self.normalizeMeanList, self.normalizeStandardList)

    def _tokenDecode(self, memory):
        idList = [self.idEnd]

        buffer = numpy.zeros((self.countLayer, self.countStep, self.sizeHidden), dtype=numpy.float32)

        while len(idList) < self.countStep:
            position = len(idList) - 1

            logit, state = self.onnxSessionDecoder.run(None, {"token": numpy.array([idList[position]], dtype=numpy.int64), "position": numpy.array(position, dtype=numpy.int64), "memory": memory, "buffer": buffer})

            buffer[:, position] = state

            idList.append(int(numpy.argmax(logit[0])))

            if idList[position + 1] == self.idEnd:
                break

        return idList

    def _partClean(self, text):
        tokenList = text.split()

        if re.search(self.patternWord, re.sub(self.patternCommand, " ", text)) is not None:
            return " ".join(tokenList)

        result = ""

        for a in range(len(tokenList)):
            isSpace = a > 0 and (tokenList[a - 1] == "\\" or (re.fullmatch(self.patternCommand, tokenList[a - 1]) is not None and tokenList[a][0:1].isalpha()))

            result += f" {tokenList[a]}" if isSpace else tokenList[a]

        return result

    def _groupEnd(self, text, start):
        depth = 0

        for a in range(start, len(text)):
            if text[a] == "{" and text[a - 1:a] != "\\":
                depth += 1
            elif text[a] == "}" and text[a - 1:a] != "\\":
                depth -= 1

            if depth == 0:
                return a

        return -1

    def _arrayUnwrap(self, text):
        match = re.fullmatch(self.patternArray, text.strip())

        if match is None or self.rowBreak in match.group(1):
            return text

        cellList = []

        content = match.group(1)

        start = 0
        depth = 0

        for a in range(len(content) + 1):
            if a < len(content) and content[a] == "{" and content[a - 1:a] != "\\":
                depth += 1
            elif a < len(content) and content[a] == "}" and content[a - 1:a] != "\\":
                depth -= 1

            if a < len(content) and (content[a] != "&" or depth != 0 or content[a - 1:a] == "\\"):
                continue

            cell = content[start:a].strip()

            while cell[0:1] == "{" and self._groupEnd(cell, 0) == len(cell) - 1:
                cell = cell[1:len(cell) - 1].strip()

            if cell != "":
                cellList.append(cell)

            start = a + 1

        return self.cellSeparator.join(cellList)

    def _textClean(self, text, isInline):
        partList = [self._partClean(part) for part in re.split(self.patternMark, self._arrayUnwrap(text))]

        mark = self.mark if isInline else self.mark * 2

        if len(partList) == 1:
            return f"{mark}{partList[0]}{mark}" if partList[0] != "" else ""

        return " ".join(partList[a] if a % 2 == 0 else f"{self.mark}{partList[a]}{self.mark}" for a in range(len(partList)) if partList[a] != "")

    def _markBuild(self):
        resultObject = {}

        with open(f"{os.path.dirname(__file__)}/character/math.txt", encoding="utf-8") as file:
            for line in file:
                match = re.match(self.patternSymbol, line)

                if match is None or match.group(3) not in self.classObject:
                    continue

                character = chr(int(match.group(1), 16))

                if character not in resultObject:
                    resultObject[character] = {}

                resultObject[character][self.classObject[match.group(3)]] = match.group(2)

        return resultObject

    def zoneExecute(self, bboxList, scale, image, bboxNumberList, isInline):
        imageCrop = self._imageCrop(bboxList, scale, image, bboxNumberList)

        if imageCrop.shape[0] == 0 or imageCrop.shape[1] == 0:
            return ""

        idList = self._tokenDecode(self.onnxSessionEncoder.run(None, {"image": self._tensorBuild(imageCrop)})[0])

        if len(idList) < 2 or idList[len(idList) - 1] != self.idEnd:
            return ""

        return self._textClean(self.tokenizer.decode(idList, skip_special_tokens=True), isInline)

    def structureCheck(self, text):
        return re.search(self.patternStructure, text) is not None or len([name for name in re.findall(self.patternCommandName, text) if name in self.structureNameList]) > 0

    def wordResolve(self, text, phraseList):
        matchList = list(re.finditer(self.patternLetter, text))

        wordList = [match.group(0) for match in matchList]

        for a in range(len(phraseList)):
            phraseWordList = re.findall(self.patternLetterWord, phraseList[a])

            count = len(phraseWordList)

            for b in range(len(wordList) - count + 1):
                indexList = [c for c in range(count) if wordList[b + c] != phraseWordList[c]]

                if count < 2 or len(indexList) == 0 or len(indexList) * 2 >= count or len([c for c in indexList if len(wordList[b + c]) != len(phraseWordList[c])]) > 0:
                    continue

                for c in range(len(indexList)):
                    wordList[b + indexList[c]] = phraseWordList[indexList[c]]

                break

        for a in range(len(matchList) - 1, -1, -1):
            text = text[0:matchList[a].start()] + wordList[a] + text[matchList[a].end():]

        return text

    def execute(self, rootNode):
        parentObject = {childNode: parentNode for parentNode in rootNode.iter() for childNode in parentNode}

        for node in [node for node in rootNode.iter() if xmlNodeTag(node) == "oMathPara"]:
            textList = [self._formulaText(childNode, self.mark * 2) for childNode in node if xmlNodeTag(childNode) == "oMath"]

            self._nodeWrite(node, f" {' '.join(textList)} ")

        nodeList = [node for node in rootNode.iter() if xmlNodeTag(node) == "oMath"]

        for a in range(len(nodeList)):
            siblingList = list(parentObject[nodeList[a]])

            index = siblingList.index(nodeList[a])

            isJoin = a > 0 and index > 0 and siblingList[index - 1] is nodeList[a - 1]

            self._nodeWrite(nodeList[a], f"{' ' if isJoin else ''}{self._formulaText(nodeList[a], self.mark)}")

    def __init__(self):
        pathModel = f"{os.path.dirname(os.path.abspath(__file__))}/model/paddle/PP-FormulaNet_plus-L"

        self.mark = "$"

        self.imageSize = 768

        self.levelInk = 200

        self.normalizeMeanList = numpy.array([0.7931, 0.7931, 0.7931], dtype=numpy.float32)
        self.normalizeStandardList = numpy.array([0.1738, 0.1738, 0.1738], dtype=numpy.float32)

        self.countLayer = 8
        self.countStep = 1024
        self.sizeHidden = 512

        self.patternCommand = r"\\[a-zA-Z]+(\{[a-zA-Z*]+\})?"
        self.patternWord = r"[^\W_]{2}"
        self.patternMark = r"(?<!\\)\$"

        self.tokenizer = Tokenizer.from_file(f"{pathModel}/tokenizer.json")

        self.idEnd = self.tokenizer.token_to_id("</s>")

        self.onnxSessionEncoder = onnxSessionBuild(f"{pathModel}/pp-formulaNet_plus-l_encoder.onnx")
        self.onnxSessionDecoder = onnxSessionBuild(f"{pathModel}/pp-formulaNet_plus-l_decoder.onnx")

        self.patternSymbol = r'\\UnicodeMathSymbol\{"([0-9A-F]+)\}\{\\(\w+)\s*\}\{\\(\w+)\}'

        self.classObject = {"mathaccent": "narrow", "mathaccentwide": "wide", "mathbotaccent": "narrow", "mathbotaccentwide": "wide", "mathover": "wide", "mathunder": "wide"}
        self.markObject = self._markBuild()

        self.patternLetter = r"(?<![^\W\d_])(?<!\\)[^\W\d_]{3,}(?![^\W\d_])"
        self.patternLetterWord = r"[^\W\d_]{3,}"
        self.patternArray = r"\\begin\s*\{array\}\s*\{[a-z|\s]*\}(.*)\\end\s*\{array\}"
        self.rowBreak = "\\\\"
        self.cellSeparator = "\\qquad "
        self.patternStructure = r"(?<!\\)[\^_]"
        self.patternCommandName = r"\\([a-zA-Z]+)"
        self.structureNameList = ["frac", "dfrac", "tfrac", "sqrt", "binom", "begin", "over", "atop", "choose", "overset", "underset", "stackrel", "overline", "underline"] + [name for nameObject in self.markObject.values() for name in nameObject.values()]
        self.defaultObject = {"nary": {"chr": chr(8747)}, "acc": {"chr": chr(770), "pos": "top"}, "groupChr": {"chr": chr(9183), "pos": "bot"}, "bar": {"pos": "bot"}, "d": {"begChr": "(", "endChr": ")", "sepChr": "|"}}
        self.escapeObject = str.maketrans({"\\": "\\backslash ", "{": "\\{", "}": "\\}", "#": "\\#", "$": "\\$", "%": "\\%", "&": "\\&"})

        self.styleScriptObject = {"script": "mathcal", "fraktur": "mathfrak", "double-struck": "mathbb", "sans-serif": "mathsf", "monospace": "mathtt"}
        self.commandUpright = "mathrm"
        self.styleWeightObject = {"p": self.commandUpright, "b": "mathbf", "bi": "boldsymbol"}
        self.styleNameList = [{"name": "DOUBLE-STRUCK", "command": "mathbb"}, {"name": "SCRIPT", "command": "mathcal"}, {"name": "FRAKTUR", "command": "mathfrak"}, {"name": "MONOSPACE", "command": "mathtt"}, {"name": "SANS-SERIF", "command": "mathsf"}, {"name": "BOLD ITALIC", "command": "boldsymbol"}, {"name": "BOLD", "command": "mathbf"}]

        self.fractionLineList = ["lin", "skw"]
        self.scriptList = ["sSub", "sSup", "sSubSup"]
        self.limitObject = {"limLow": "underset", "limUpp": "overset"}
        self.markList = ["acc", "groupChr"]
