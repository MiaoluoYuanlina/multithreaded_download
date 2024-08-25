"""
原仓库 https://github.com/HViktorTsoi/MultithreadingDownloader


"""
import multiprocessing
import sys
import threading
import time
from contextlib import closing

import requests
import requests.adapters


# ----------------------------------------------------------------------------------------------------------------------
#十六进制终端输出
def rgb_to_ansi256(r, g, b):
    """
    将 RGB 值转换为 ANSI 256 色码。
    """
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return round(((r - 8) / 247) * 24) + 232

    return 16 + (36 * round(r / 255 * 5)) + (6 * round(g / 255 * 5)) + round(b / 255 * 5)


def RGB_text(text, hex_color):
    """
    将文本用指定的十六进制颜色显示。
    """
    # 提取 RGB 值
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)

    # 将 RGB 转换为 ANSI 256 色码
    ansi_color = rgb_to_ansi256(r, g, b)

    # 构建带颜色的字符串
    colored_text = f"\033[38;5;{ansi_color}m{text}\033[0m"

    return colored_text


# 示例用法
#text = "这是使用#FF5733颜色的文本"
#hex_color = "#FF5733"
#print(RGB_text(text, hex_color))
# ----------------------------------------------------------------------------------------------------------------------


class Downloader:
    """多线程下载器

    用Downloader(目标URL, 保存的本地文件名)的方式实例化

    用start()开始下载

    样例:

    downloader=Downloader(
        url="http://file.example.com/somedir/filename.ext",
        file="/path/to/file.ext"
    )

    downloader.start()
    """

    def __init__(self,
                 threads_num=20,
                 chunk_size=1024 * 128,
                 timeout=0,
                 enable_log=True
                 ):
        """初始化

            :param threads_num=20: 下载线程数

            :param chunk_size=1024*128: 下载线程以流方式请求文件时的chunk大小

            :param timeout=60: 下载线程最多等待的时间
        """
        self.threads_num = threads_num
        self.chunk_size = chunk_size
        self.timeout = timeout if timeout != 0 else threads_num  # 超时时间正比于线程数

        self.__content_size = 0
        self.__file_lock = threading.Lock()
        self.__threads_status = {}
        self.__crash_event = threading.Event()
        self.__msg_queue = multiprocessing.Queue()

        self.__enable_log = enable_log
        self.__logger = Logger(msgq=self.__msg_queue) if enable_log else None

        requests.adapters.DEFAULT_RETRIES = 2

    def __establish_connect(self, url):
        """建立连接
        """

        print(f"{RGB_text("╔═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════", "#FF5733")}")
        #print(f"{RGB_text("╠═⇒", "#FF5733")} {RGB_text("URL: {}".format(text), "#1E90FF")}")
        print(f"{RGB_text("╠═⇒", "#FF5733")} {RGB_text("建立连接中......", "#8A2BE2")}")
        hdr = requests.head(url).headers
        self.__content_size = int(hdr["Content-Length"])
        print(f"{RGB_text("╠═⇒", "#FF5733")} {RGB_text("连接已经建立!", "#6A5ACD")}")
        if self.__content_size <= 1024 * 1024:
            print(f"{RGB_text("╠═⇒", "#FF5733")} {RGB_text(f"文件大小：{round(self.__content_size / 1024, 1)}KB ⇄ {self.__content_size}Bit", "#8B0000")}")
        elif self.__content_size <= 1024 * 1024 * 1024:
            print(f"{RGB_text("╠═⇒", "#FF5733")} {RGB_text(f"文件大小：{round(self.__content_size / 1024 / 1024, 1)}MB ⇄ {self.__content_size}Bit", "#8B0000")}")
        elif self.__content_size <= 1024 * 1024 * 1024 * 1024:
            print(f"{RGB_text("╠═⇒", "#FF5733")} {RGB_text(f"文件大小：{round(self.__content_size / 1024 / 1024 / 1024, 1)}GB ⇄ {self.__content_size}Bit", "#8B0000")}")

    def __page_dispatcher(self):
        """分配每个线程下载的页面大小
        """
        # 基础分页大小
        basic_page_size = self.__content_size // self.threads_num
        start_pos = 0
        # 分配给各线程的页面大小
        while start_pos + basic_page_size < self.__content_size:
            yield {
                'start_pos': start_pos,
                'end_pos': start_pos + basic_page_size
            }
            start_pos += basic_page_size + 1
        # 最后不完整的一页补齐
        yield {
            'start_pos': start_pos,
            'end_pos': self.__content_size - 1
        }

    def __download(self, url, file, page):
        """下载

            :param url="": 下载的目标URL

            :param file: 保存在本地的目标文件

            :param page: 下载的分页信息 start_pos:开始字节 end_pos:结束字节
        """
        # 当前线程负责下载的字节范围
        headers = {
            "Range": "bytes={}-{}".format(page["start_pos"], page["end_pos"])
        }
        thread_name = threading.current_thread().name
        # 初始化当前进程信息列表
        self.__threads_status[thread_name] = {
            "page_size": page["end_pos"] - page["start_pos"],
            "page": page,
            "status": 0,
        }
        try:
            # 以流的方式进行get请求
            with closing(requests.get(
                    url=url,
                    headers=headers,
                    stream=True,
                    timeout=self.timeout
            )) as response:
                for data in response.iter_content(chunk_size=self.chunk_size):
                    # 向目标文件中写入数据块,此处需要同步锁
                    with self.__file_lock:
                        # 查找文件写入位置
                        file.seek(page["start_pos"])
                        # 写入文件
                        file.write(data)
                    # 数据流每向前流动一次,将指针位置同时前移
                    page["start_pos"] += len(data)
                    self.__threads_status[thread_name]["page"] = page
                    if self.__enable_log:
                        self.__msg_queue.put(self.__threads_status)

        except requests.RequestException as exception:
            print("XXX From {}: ".format(exception), file=sys.stderr)
            self.__threads_status[thread_name]["status"] = 1
            if self.__enable_log:
                self.__msg_queue.put(self.__threads_status)
            # 设置crash_event标记为1
            self.__crash_event.set()

    def __run(self, url, target_file, urlhandler):
        """执行下载线程

            :param url="": 下载的目标URL

            :param target_file="": 保存在本地的目标文件名（完整路径，包括文件扩展名）

            :param urlhandler: 目标URL的处理器，用来处理重定向或Content-Type不存在等问题
        """
        thread_list = []
        self.__establish_connect(url)
        self.__threads_status["url"] = url
        self.__threads_status["target_file"] = target_file
        self.__threads_status["content_size"] = self.__content_size
        self.__crash_event.clear()
        # 处理url
        url = urlhandler(url)
        with open(target_file, "wb+") as file:
            for page in self.__page_dispatcher():
                thd = threading.Thread(
                    target=self.__download, args=(url, file, page)
                )
                thd.start()
                thread_list.append(thd)
            for thd in thread_list:
                thd.join()
        self.__threads_status = {}
        # 判断是否有线程失败
        if self.__crash_event.is_set():
            raise Exception("下载未成功！！！")

    def start(self, url, target_file, urlhandler=lambda u: u):
        """开始下载

            :param url="": 下载的目标URL

            :param target_file="": 保存在本地的目标文件名（完整路径，包括文件扩展名）

            :param urlhandler=lambdau:u: 目标URL的处理器，用来处理重定向或Content-Type不存在等问题
        """
        # 记录下载开始时间
        start_time = time.time()

        # 如果允许log
        if self.__enable_log:
            # logger进程
            self.__logger.start()
            # 开始下载
            self.__run(url, target_file, urlhandler)
            # 结束logger进程
            self.__logger.join(0.5)
        else:
            # 直接开始下载
            self.__run(url, target_file, urlhandler)

        # 记录下载总计用时
        span = time.time() - start_time
        print(f"{RGB_text("╚═>", "#FF5733")} {RGB_text("下载完成啦~","#FF0000")} {RGB_text(f"总计用时:{round(span - 0.5,2)}s","#008B8B")}")



class Logger(multiprocessing.Process):
    """日志进程

    记录每个线程的下载状态以及文件下载状态
    """

    def __init__(self, msgq):
        """初始化日志记录器

            :param msgq: 下载进程与日志进程通信的队列
        """
        multiprocessing.Process.__init__(self, daemon=True)
        self.__threads_status = {}
        self.__msg_queue = msgq

    def __log_metainfo(self):
        """输出文件元信息
        """

        # print(RGB_text("text", "#FF5733"))
        print(RGB_text("╠═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════",
                       "#FF5733"))
        print(RGB_text("╠═╦═⇒文件原信息:↴ ", "#FF5733"))
        print(f"{RGB_text("╟ ╠═⇒ ", "#FF5733")} {RGB_text(f"URL: {self.__threads_status["url"]}","#1E90FF")}")
        print(f"{RGB_text("╟ ╚═⇒ ", "#FF5733")} {RGB_text(f"文件名: {self.__threads_status["target_file"]}","#FFA07A")}")

        # if self.__threads_status["content_size"] <= 1024 * 1024:
        #     print(f"{RGB_text("| └ -", "#FF5733")} 文件大小: {round(self.__threads_status["content_size"] / 1024, 2)}KB")
        # elif self.__threads_status["content_size"] <= 1024 * 1024 * 1024:
        #     print(f"{RGB_text("| └ -", "#FF5733")} 文件大小: {round(self.__threads_status["content_size"] / 1024 / 1024, 2)}MB")
        # elif self.__threads_status["content_size"] <= 1024 * 1024 * 1024 * 1024:
        #     print(f"{RGB_text("| └ -", "#FF5733")} 文件大小: {round(self.__threads_status["content_size"] / 1024 / 1024 / 1024, 2)}GB")

    def __log_threadinfo(self):
        """输出各线程下载状态信息
        """
        downloaded_size = 0
        for thread_name, thread_status in self.__threads_status.items():
            if thread_name not in ("url", "target_file", "content_size"):
                page_size = thread_status["page_size"]
                page = thread_status["page"]
                thread_downloaded_size = page_size - \
                                         (page["end_pos"] - page["start_pos"])
                downloaded_size += thread_downloaded_size
                self.__print_thread_status(
                    thread_name, thread_status["status"], page_size,
                    page, thread_downloaded_size
                )
        self.__print_generalinfo(downloaded_size)

    def __print_thread_status(self, thread_name, status, page_size, page, thread_downloaded_size):
        """打印线程信息

            :param thread_name: 线程名

            :param status: 线程执行状态

            :param page_size: 分页大小

            :param page: 分页信息

            :param thread_downloaded_size: 线程已经下载的字节数
        """
        #print("")
        if status == 0:
            if page["start_pos"] < page["end_pos"]:
                print(f"{RGB_text("╠═>", "#FF5733")} {RGB_text(thread_name,"#00FF7F")} {RGB_text(f"已下载: {round(thread_downloaded_size / 1024,2)}KB / 需下载: {round(page_size / 1024,2)}KB","#BA55D3")}")
            else:
                print(f"{RGB_text("╠═>", "#FF5733")} {RGB_text(format(thread_name),"#00FF7F")} {RGB_text("下载完成！","#8A2BE2")}")
        elif status == 1:
            print("|XXX {} 粉碎".format(
                thread_name
            ), file=sys.stderr)

    def __print_generalinfo(self, downloaded_size):
        """打印文件整体下载信息

            :param downloaded_size: 整个文件已经下载的字节数
        """
        if downloaded_size <= 1024 * 1024:
            print(
                f"{RGB_text("╠═>", "#FF5733")} {RGB_text(f"共计已下载: {round(downloaded_size / 1024, 2)}KB / 共计需下载: {round(self.__threads_status["content_size"] / 1024,2)}KB","#FFD700")}")
        elif downloaded_size <= 1024 * 1024 * 1024:
            print(
                f"{RGB_text("╠═>", "#FF5733")} {RGB_text(f"共计已下载: {round(downloaded_size / 1024 / 1024, 2)}MB / 共计需下载: {round(self.__threads_status["content_size"] / 1024,2)}MB","#FFD700")}")
        elif downloaded_size <= 1024 * 1024 * 1024 * 1024:
            print(
                f"{RGB_text("╠══>", "#FF5733")} {RGB_text(f"共计已下载: {round(downloaded_size / 1024 / 1024 / 1024, 2)}GB / 共计需下载: {round(self.__threads_status["content_size"] / 1024,2)}GB","#FFD700")}")

    #╔╦╗  ═ㅒㅐ
    #╠╬╣  ╠══╦╦═
    #╚╩╝  ╟  ╢╫
    def run(self):
        while True:
            if self.__msg_queue.qsize() != 0:
                #print("\033c")
                self.__threads_status = self.__msg_queue.get()
                self.__log_metainfo()
                self.__log_threadinfo()


if __name__ == '__main__':
    DOWNLOADER = Downloader(threads_num=2)
    DOWNLOADER.start(
        #url="https://builds.bepinex.dev/projects/bepinex_be/571/BepInEx_UnityMono_x64_3a54f7e_6.0.0-be.571.zip",
        url="https://objects.githubusercontent.com/github-production-release-asset-2e65be/572568692/e1c59312-6123-45ef-96f2-01f36d37bdc4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=releaseassetproduction%2F20240825%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20240825T151559Z&X-Amz-Expires=300&X-Amz-Signature=7c172e226d92317da29f3ca1b082e4d89f73ae0593510eb84d05a1b6d704e64d&X-Amz-SignedHeaders=host&actor_id=0&key_id=0&repo_id=572568692&response-content-disposition=attachment%3B%20filename%3Dpatch-20230119.7z&response-content-type=application%2Foctet-stream",
        target_file="C:/Users/XiaoM/Desktop/1/1.zip",
    )
