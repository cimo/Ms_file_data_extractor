import sys
import os
import numpy
from tokenizers import Tokenizer

sys.dont_write_bytecode = True

# Source
from helper import onnxSessionBuild, tokenScore, wordKey, characterHyphenMark

class Hyphen:
    def _score(self, textBefore, word, textAfter):
        encodeObject = self.tokenizer.encode(f"{textBefore}{word}{textAfter}")

        start = len(textBefore)
        end = start + len(word)

        indexList = [a for a in range(len(encodeObject.ids)) if encodeObject.offsets[a][1] > start and encodeObject.offsets[a][0] < end and encodeObject.offsets[a][1] > encodeObject.offsets[a][0]]

        result = 0.0

        for a in range(len(indexList)):
            tensor = numpy.full((1, self.countToken), self.idPad, dtype=numpy.int64)
            tensorMask = numpy.zeros((1, self.countToken), dtype=numpy.int64)

            tensor[0][0:len(encodeObject.ids)] = encodeObject.ids
            tensor[0][indexList[a]] = self.idMask

            tensorMask[0][0:len(encodeObject.ids)] = 1

            result += tokenScore(self.onnxSession.run(None, {"input_ids": tensor, "attention_mask": tensorMask, "mask_index": numpy.array([[indexList[a]]], dtype=numpy.int64)})[0][0], encodeObject.ids[indexList[a]])

        return result

    def _contextBuild(self, tokenList, index, word):
        countBefore = self.countBefore
        countAfter = self.countAfter

        textBefore = ""
        textAfter = ""

        isFit = False

        while isFit == False:
            textBefore = " ".join(self._tokenPlain(token) for token in tokenList[max(0, index - countBefore):index]) + " "
            textAfter = " " + " ".join(self._tokenPlain(token) for token in tokenList[index + 1:index + 1 + countAfter])

            isFit = len(self.tokenizer.encode(f"{textBefore}{word}{textAfter}").ids) <= self.countToken or (countBefore == 0 and countAfter == 0)

            countBefore = max(0, countBefore - 1)
            countAfter = max(0, countAfter - 1)

        return textBefore, textAfter

    def _tokenPlain(self, token):
        return token.replace(characterHyphenMark, "")

    def execute(self, text, wordList):
        tokenList = text.split(" ")

        for a in range(len(tokenList)):
            if characterHyphenMark not in tokenList[a]:
                continue

            partList = tokenList[a].split(characterHyphenMark)

            tokenHyphen = "".join(partList)
            tokenJoined = "".join(partList[b][0:-1] if b < len(partList) - 1 else partList[b] for b in range(len(partList)))

            if wordKey(tokenJoined) in wordList:
                tokenList[a] = tokenJoined
            elif wordKey(tokenHyphen) in wordList or len(self.tokenizer.encode(tokenHyphen).ids) > self.countToken:
                tokenList[a] = tokenHyphen
            else:
                textBefore, textAfter = self._contextBuild(tokenList, a, tokenHyphen)

                tokenList[a] = tokenJoined if self._score(textBefore, tokenJoined, textAfter) > self._score(textBefore, tokenHyphen, textAfter) else tokenHyphen

        return " ".join(tokenList)

    def __init__(self):
        pathModel = f"{os.path.dirname(os.path.abspath(__file__))}/model/jhu-clsp/mmBERT-small"

        self.countBefore = 12
        self.countAfter = 8
        self.countToken = 64

        self.tokenizer = Tokenizer.from_file(f"{pathModel}/tokenizer.json")

        self.idMask = self.tokenizer.token_to_id("<mask>")
        self.idPad = self.tokenizer.token_to_id("<pad>")

        self.onnxSession = onnxSessionBuild(f"{pathModel}/model_mask.onnx")
