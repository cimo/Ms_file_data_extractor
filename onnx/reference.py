import unicodedata
import icu

class Reference:
    def _currencyBuild(self):
        resultList = []

        localeObject = icu.Locale.getAvailableLocales()

        for name in localeObject:
            numberFormat = icu.NumberFormat.createCurrencyInstance(localeObject[name])

            code = numberFormat.getCurrency()

            textFormat = numberFormat.format(1)

            symbol = ""

            for a in range(len(textFormat)):
                category = unicodedata.category(textFormat[a])

                if category == "Sc" or category[0] == "L":
                    symbol += textFormat[a]

            if code == "XXX":
                continue

            if len(code) == 3 and code not in resultList:
                resultList.append(code)

            if len(symbol) > 0 and symbol not in resultList and (len(symbol) > 1 or self._casedCheck(symbol) == False):
                resultList.append(symbol)

            textName = ""

            textFull = str(icu.NumberFormatter.withLocale(localeObject[name]).unit(icu.CurrencyUnit(code)).unitWidth(icu.UNumberUnitWidth.FULL_NAME).formatInt(2))

            for a in range(len(textFull)):
                textName += " " if unicodedata.category(textFull[a])[0] == "N" else textFull[a]

            textName = " ".join(self._wordList(textName))

            if len(textName) > 0 and textName not in resultList:
                resultList.append(textName)

        return resultList

    def _unitBuild(self):
        resultList = []

        unitList = []

        typeList = icu.MeasureUnit.getAvailableTypes()

        for typeName in typeList:
            if typeName == "currency":
                continue

            unitTypeList = icu.MeasureUnit.getAvailable(typeName)

            for a in range(len(unitTypeList)):
                if unitTypeList[a].getSubtype() not in self.unitSkipList:
                    unitList.append(unitTypeList[a])

        localeObject = icu.Locale.getAvailableLocales()

        for name in localeObject:
            if "_" in name:
                continue

            formatter = icu.NumberFormatter.withLocale(localeObject[name]).unitWidth(icu.UNumberUnitWidth.SHORT)

            for a in range(len(unitList)):
                textFull = str(formatter.unit(unitList[a]).formatInt(2))

                textUnit = ""

                for b in range(len(textFull)):
                    if unicodedata.category(textFull[b])[0] not in ["N", "Z", "C"]:
                        textUnit += textFull[b]

                if len(textUnit) > 0 and textUnit not in resultList:
                    resultList.append(textUnit)

        return resultList

    def _wordList(self, text):
        resultList = []

        word = ""

        for a in range(len(text) + 1):
            if a < len(text) and unicodedata.category(text[a])[0] not in ["Z", "P", "C"]:
                word += text[a]

                continue

            if len(word) > 0:
                resultList.append(word)

                word = ""

        return resultList

    def _casedCheck(self, text):
        for a in range(len(text)):
            if unicodedata.category(text[a]) in ["Lu", "Ll", "Lt"]:
                return True

        return False

    def _joinCheck(self, word, tokenList):
        reachList = [True]

        for a in range(len(word)):
            reachList.append(False)

        for a in range(len(word)):
            if reachList[a] == False:
                continue

            for b in range(len(tokenList)):
                if self._casedCheck(tokenList[b]) == False and word.startswith(tokenList[b], a):
                    reachList[a + len(tokenList[b])] = True

        return reachList[len(word)]

    def _datePatternBuild(self):
        resultList = []

        for a in range(len(self.dateLetterList)):
            letterDay = self.dateLetterList[a][0]
            letterMonth = self.dateLetterList[a][1]
            letterYear = self.dateLetterList[a][2]

            for countDay in [1, 2]:
                for countMonth in [1, 2]:
                    for countYear in [1, 2, 4]:
                        day = letterDay * countDay
                        month = letterMonth * countMonth
                        year = letterYear * countYear

                        patternList = [day + month + year, month + day + year, year + month + day, month + year, year + month, day + month, month + day]

                        for b in range(len(patternList)):
                            if (b < 3 or len(patternList[b]) >= 4) and patternList[b] not in resultList:
                                resultList.append(patternList[b])

        return resultList

    def dateLetterCheck(self, text):
        wordList = self._wordList(text)

        for a in range(len(wordList)):
            for b in range(len(wordList[a])):
                isLetter = False

                for c in range(len(self.dateLetterList)):
                    if wordList[a][b].upper() in self.dateLetterList[c]:
                        isLetter = True

                if isLetter == False:
                    return False

        return len(wordList) > 0

    def datePatternCheck(self, text):
        return "".join(self._wordList(text)).upper() in self.datePatternList

    def markFind(self, text):
        resultList = []

        index = 0

        while index < len(text):
            tokenBest = ""
            isMark = False

            if index == 0 or text[index] not in ["(", "["] or unicodedata.category(text[index - 1]) not in ["Lu", "Ll", "Nd"]:
                for a in range(len(self.markCheckedList)):
                    if text.startswith(self.markCheckedList[a], index) and len(self.markCheckedList[a]) > len(tokenBest):
                        tokenBest = self.markCheckedList[a]
                        isMark = True

                for a in range(len(self.markUncheckedList)):
                    if text.startswith(self.markUncheckedList[a], index) and len(self.markUncheckedList[a]) > len(tokenBest):
                        tokenBest = self.markUncheckedList[a]
                        isMark = False

            if tokenBest == "":
                index += 1

                continue

            resultList.append({"index": index, "length": len(tokenBest), "isMark": isMark, "text": tokenBest})

            index += len(tokenBest)

        return resultList

    def markValidCheck(self, tokenList):
        isUnchecked = False

        for a in range(len(tokenList)):
            if tokenList[a]["text"] in self.markSoloList:
                return True

            if tokenList[a]["isMark"] == False:
                isUnchecked = True

        return len(tokenList) > 1 and isUnchecked

    def unitCheck(self, text):
        return "".join(self._wordList(text)) in self.unitObject

    def captionCheck(self, text, tokenList):
        wordList = self._wordList(text)

        if " ".join(wordList) in tokenList:
            return True

        for a in range(len(wordList)):
            if wordList[a] not in tokenList and self._joinCheck(wordList[a], tokenList) == False:
                return False

        return len(wordList) > 0

    def sentenceEndCheck(self, text):
        text = text.strip()

        return len(text) > 0 and icu.Char.hasBinaryProperty(text[len(text) - 1], icu.UProperty.S_TERM)

    def __init__(self):
        self.dateCaptionList = [
            "DD", "MM", "YY", "YYYY",
            "TT", "JJ", "JJJJ",
            "GG", "AA", "AAAA",
            "HH", "SS",
            "年", "月", "日", "時", "分", "秒",
            "令和", "平成", "昭和", "大正", "明治",
            "년", "월", "일", "시", "분", "초"
        ]

        self.dateLetterList = [
            ["D", "M", "Y"],
            ["T", "M", "J"],
            ["G", "M", "A"],
            ["J", "M", "A"],
            ["D", "M", "A"],
            ["D", "M", "J"]
        ]

        self.datePatternList = self._datePatternBuild()

        self.markCheckedList = ["[x]", "[X]", "[✓]", "[✔]", "[*]", "(x)", "(X)", "(✓)", "(✔)", "(*)", "☑", "☒", "■", "●", "◉", "✓", "✔", "◼", "⬛"]
        self.markUncheckedList = ["[ ]", "[　]", "( )", "(　)", "☐", "□", "○", "◯", "〇", "▢", "◻", "⬜"]
        self.markSoloList = ["[x]", "[X]", "[✓]", "[✔]", "[ ]", "[　]", "☑", "☒", "☐"]

        self.leaderList = [".", "…", "‥", "·", "・", "⋯"]

        self.currencyList = self._currencyBuild()

        self.unitSkipList = ["gasoline-energy-density"]

        self.unitObject = {}

        unitList = self._unitBuild()

        for a in range(len(unitList)):
            self.unitObject[unitList[a]] = True
