import asyncio
import uuid
import requests
import hashlib
import argparse
import time
import re
import math
import aiohttp
from aiohttp import TCPConnector


YOUDAO_URL = 'https://openapi.youdao.com/api'
APP_KEY = 'Your APP KEY'
APP_SECRET = 'Your APP SECRET'
MAX_IN_LINE = 18


def encrypt(signStr):
    hash_algorithm = hashlib.sha256()
    hash_algorithm.update(signStr.encode('utf-8'))
    return hash_algorithm.hexdigest()


def truncate(q):
    if q is None:
        return None
    size = len(q)
    return q if size <= 20 else q[0:10] + str(size) + q[size - 10:size]


def do_request(data):
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    return requests.post(YOUDAO_URL, data=data, headers=headers)


def connect(q):
    data = {}
    data['from'] = 'en'
    data['to'] = 'zh-CHS'
    data['signType'] = 'v3'
    curtime = str(int(time.time()))
    data['curtime'] = curtime
    salt = str(uuid.uuid1())
    signStr = APP_KEY + truncate(q) + salt + curtime + APP_SECRET
    sign = encrypt(signStr)
    data['appKey'] = APP_KEY
    data['q'] = q
    data['salt'] = salt
    data['sign'] = sign

    response = do_request(data)
    contentType = response.headers['Content-Type']
    if contentType == "audio/mp3":
        millis = int(round(time.time() * 1000))
        filePath = "./" + str(millis) + ".mp3"
        fo = open(filePath, 'wb')
        fo.write(response.content)
        fo.close()
    else:
        result = response.json()
        if result['errorCode'] == '0':
            return result['translation']
        else:
            raise Exception(f"errorCode: {result['errorCode']}")


def is_word(line: str):
    """时间轴，和序号不需要翻译"""
    time_line = re.compile('[0-9].*?-->.*?[0-9]')
    if line.strip().isdigit() or time_line.fullmatch(line.strip()) or (not line.strip()):
        return False
    else:
        return True


def find_timeline(line: str):
    time_line = re.compile("^([0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3}) --> ([0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3})$")
    return time_line.findall(line.strip())


def is_sentence_end(line: str):
    """是句子的结尾"""
    ends = ['.', '?', '!', '……']
    for end in ends:
        if line.endswith(end):
            return True
    return False


class SentenceEndError(Exception):
    pass


class NotTranslatedSentence(Exception):
    pass


class SentenceBlock:
    """一个完整的句子段落，包括时间轴"""

    def __init__(self):
        self.__sentence = ''  # 句子内容， 不包含时间轴
        self.lines = []  # 需要输出到文本的内容，包括时间轴
        self.__is_end = False
        self.__is_translated = False
        self.timelines_index = []  # 时间轴的位置
        self.__to_sentence = ''  # 翻译后的句子
        self.times = []  # 时间线的时间点

    def append_lines(self, line: str):
        if is_word(line):
            self.combine_sentence(line)
        else:
            time_ = find_timeline(line)
            if time_:
                self.lines.append(line)
                self.timelines_index.append(len(self.lines) - 1)
                self.times.extend(time_)

    def combine_sentence(self, s):
        if not self.__is_end:
            if self.__sentence:
                self.__sentence += ' ' + s
            else:
                self.__sentence += s
            if is_sentence_end(s):
                self.__is_end = True
            else:
                self.__is_end = False
        else:
            raise SentenceEndError('The sentence is ended')

    def get_raw_sentence(self):
        return self.__sentence

    def set_to_sentence(self, sent):
        self.__to_sentence = sent

    def __split_sentence(self):
        """把长句子拆分"""
        len_sentence = len(self.__to_sentence)
        ret = []
        i = 0
        j = min(i + MAX_IN_LINE, len_sentence)
        while i < len_sentence:
            if j != len_sentence and self.__to_sentence[j] in {'。', '，', '？'}:
                j += 1
            ret.append(self.__to_sentence[i:j])
            i = j
            j = j + MAX_IN_LINE
            if j > len_sentence:
                j = len_sentence

        return ret

    def reinsert_sentence(self):
        """重新插入翻译后的句子到时间轴"""
        if self.__to_sentence:
            raw_size = len(self.timelines_index)
            if raw_size == 1:
                self.lines.insert(self.timelines_index[0] + 1, self.__to_sentence)
            else:
                stn_lines = self.__split_sentence()  # 句子拆分成行

                self.combine_timelines(math.ceil(len(stn_lines) / 2))  # 重新划分时间线

                if len(stn_lines) % 2 == 0 and len(stn_lines) >= 2:
                    self.lines.extend(stn_lines[-2:])
                    stn_lines = stn_lines[:-2]
                else:
                    self.lines.append(stn_lines.pop())

                if len(stn_lines):
                    j = len(stn_lines) - 1
                    for i in range(len(self.timelines_index) - 2, -1, -1):
                        self.lines.insert(self.timelines_index[i] + 1, stn_lines[j]+'\r')
                        self.lines.insert(self.timelines_index[i] + 1, stn_lines[j - 1])
                        self.timelines_index[i + 1] += (2*(i+1))
                        j -= 2
        else:
            raise NotTranslatedSentence()

    def combine_timelines(self, n):
        """
        组合原来的时间轴，减少时间分段
        :param n:  减少到几段
        :return:
        """
        while len(self.times) > n:
            self.times[0] = (self.times[0][0], self.times[1][-1])
            self.times.remove(self.times[1])
            # 更新索引
            self.timelines_index.pop()
        # 更新lines
        index = self.timelines_index[0]
        for timeline in self.__gen_timelines():
            self.lines[index] = timeline
            index += 1
        self.lines = self.lines[0:index]

    def __gen_timelines(self):
        """更加时间生成时间轴"""
        for timeline in self.times:
            start = timeline[0]
            end = timeline[-1]
            yield f"{start} --> {end}"

    def __str__(self):
        return self.__sentence

    def __repr__(self):
        return self.__sentence


async def main(file):
    # read_file
    out_lines = []
    out_path = file.replace('.srt', '-zh.srt')
    with open(file, 'r') as f:
        sentence_block = SentenceBlock()
        for line in f:
            line = line.strip()
            sentence_block.append_lines(line)
            if is_sentence_end(line):
                # 保存句子
                out_lines.append(sentence_block)
                # 开启新的实例
                sentence_block = SentenceBlock()
    # 翻译
    async with aiohttp.ClientSession(connector=TCPConnector(ssl=False)) as session:
        print(f'总共{len(out_lines)}句')
        i = 1
        for block in out_lines:
            raw_sentence = block.get_raw_sentence()
            data = {'from': 'en', 'to': 'zh-CHS', 'signType': 'v3'}
            curtime = str(int(time.time()))
            data['curtime'] = curtime
            salt = str(uuid.uuid1())
            signStr = APP_KEY + truncate(raw_sentence) + salt + curtime + APP_SECRET
            sign = encrypt(signStr)
            data['appKey'] = APP_KEY
            data['q'] = raw_sentence
            data['salt'] = salt
            data['sign'] = sign
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}

            async with session.post(YOUDAO_URL, data=data, headers=headers) as response:
                result = await response.json()
                if result['errorCode'] == '0':
                    block.set_to_sentence(result['translation'][0])
                    print(f'\r网络翻译中: {(i / len(out_lines)) * 100 : .2f}%', end="")
                    i += 1
                else:
                    print(result['errorCode'])
                    raise Exception(f"errorCode: {result['errorCode']}")

    print("\r")
    print("翻译完成，组合文本")
    j = 1
    for block in out_lines:
        block.reinsert_sentence()
        for i in range(len(block.timelines_index)-1, -1, -1):
            block.lines.insert(block.timelines_index[i], str(j+i))
            block.timelines_index[i] += (i+1)
        j += len(block.timelines_index)
    print("准备写入")
    # 写入文本
    with open(out_path, 'w+') as f:
        for block in out_lines:
            f.write('\r'.join(block.lines))
            f.write('\r\r')
    return "OK"

if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument('content', help='file to be translated')
        parser.add_argument('-w', '--world', help='the content is str not a file', action="store_true")
        args = parser.parse_args()
        loop = asyncio.get_event_loop()
        if args.world:
            print(connect(str(args.content)))
        else:
            print(loop.run_until_complete(main(args.content)))

    except Exception as e:
        raise
        # print(e)
        # exit(1)
