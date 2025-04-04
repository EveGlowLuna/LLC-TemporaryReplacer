#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Limbus Company本地化工具

这是一个用于安装和管理Limbus Company游戏本地化内容的图形界面工具。
主要功能包括：
- 选择和安装自定义字体
- 下载并安装本地化资源包
- 管理游戏语言配置
- 提供完整的安装和卸载功能

作者: YangChen114514
重构版
"""

import sys
import os
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
import py7zr
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog,
    QPushButton, QLabel, QTextEdit, QProgressBar,
    QMessageBox
)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import (
    QFile, QIODevice, QThread, Signal, 
    QMutex, QWaitCondition, QMutexLocker
)
from PySide6.QtGui import QTextCursor

class DownloadThread(QThread):
    """下载线程类
    
    使用QThread处理文件下载，支持进度回调和取消操作。
    
    信号:
        progress_updated: 下载进度更新信号
        download_finished: 下载完成信号
        download_error: 下载错误信号
    """
    
    progress_updated = Signal(int)
    download_finished = Signal(str)
    download_error = Signal(str)
    
    def __init__(self, url, save_path, logger):
        """初始化下载线程
        
        Args:
            url: 下载文件的URL
            save_path: 保存路径
            logger: 日志记录器实例
        """
        super().__init__()
        self.url = url
        self.save_path = save_path
        self.logger = logger
        self._stop_flag = False
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        
    def stop(self):
        """停止下载"""
        with QMutexLocker(self._mutex):
            self._stop_flag = True
            self._condition.wakeAll()
        
    def run(self):
        """执行下载操作
        
        使用requests库下载文件，支持进度回调和取消操作。
        """
        try:
            # 设置超时为30秒
            response = requests.get(self.url, stream=True, timeout=(5, 30))
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            block_size = 1024  # 1 KB
            downloaded_size = 0

            self.logger.info(f"开始下载文件: {os.path.basename(self.save_path)}")
            self.logger.info(f"文件大小: {total_size / (1024*1024):.2f} MB")

            with open(self.save_path, 'wb') as file:
                for data in response.iter_content(block_size):
                    # 检查停止标志
                    with QMutexLocker(self._mutex):
                        if self._stop_flag:
                            self.logger.info("下载已取消")
                            self.download_error.emit("下载已取消")
                            return
                            
                    if data:
                        file.write(data)
                        downloaded_size += len(data)
                        if total_size > 0:
                            progress = int((downloaded_size / total_size) * 100)
                            self.progress_updated.emit(progress)
                            
            self.download_finished.emit(self.save_path)
            
        except requests.RequestException as e:
            error_msg = f"下载失败: {str(e)}"
            self.logger.error(error_msg)
            self.download_error.emit(error_msg)
        except Exception as e:
            error_msg = f"下载过程中发生错误: {str(e)}"
            self.logger.error(error_msg)
            self.download_error.emit(error_msg)

class MainWindow(QMainWindow):
    """主窗口类
    
    负责处理UI初始化、事件绑定和主要业务逻辑的实现。
    """
    
    def __init__(self):
        """初始化主窗口"""
        super().__init__()
        self._ui_mutex = QMutex()
        self._init_ui()
        self._init_variables()
        self.setup_ui()
        self.setup_events()
        self.load_path_record()
        self.detect_steam_path()
        self.ui.show()
        
    def _init_ui(self):
        """初始化UI界面"""
        # 获取UI文件的路径
        if getattr(sys, 'frozen', False):
            # 如果是打包后的可执行文件
            base_path = sys._MEIPASS
        else:
            # 如果是开发环境
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        ui_path = os.path.join(base_path, "llc-tr-ui.ui")
        ui_file = QFile(ui_path)
        
        if not ui_file.open(QIODevice.ReadOnly):
            error_msg = f"无法打开UI文件 {ui_file.fileName()}: {ui_file.errorString()}"
            QMessageBox.critical(self, "错误", error_msg)
            sys.exit(1)
            
        loader = QUiLoader()
        self.ui = loader.load(ui_file)
        ui_file.close()
        
        if not self.ui:
            error_msg = f"UI加载失败: {loader.errorString()}"
            QMessageBox.critical(self, "错误", error_msg)
            sys.exit(1)
            
        self.ui.setWindowTitle("Limbus Company临时本地化工具")
        
    def _init_variables(self):
        """初始化成员变量"""
        self.font_path = ""
        self.game_path = ""
        self.download_thread = None
        self._is_downloading = False
        self.install_config = None
        
    def download_install_config(self):
        """下载安装配置文件"""
        try:
            self.logger.info("正在获取最新安装配置信息...")
            config_url = "https://raw.githubusercontent.com/EveGlowLuna/LLC-TemporaryReplacer/main/install_info.json"
            response = requests.get(config_url, timeout=10)
            response.raise_for_status()
            self.install_config = response.json()
            self.logger.info("成功获取安装配置信息")
            return True
        except requests.exceptions.ConnectionError as e:
            error_msg = "网络连接错误，无法获取安装配置"
            self.show_error("更新失败", error_msg)
            return False
        except requests.exceptions.Timeout as e:
            error_msg = "获取安装配置超时，请检查网络连接"
            self.show_error("更新失败", error_msg)
            return False
        except requests.exceptions.RequestException as e:
            error_msg = f"获取安装配置时发生错误: {str(e)}"
            self.show_error("更新失败", error_msg)
            return False
        except json.JSONDecodeError as e:
            error_msg = "安装配置文件格式错误"
            self.show_error("更新失败", error_msg)
            return False
        except Exception as e:
            error_msg = f"获取安装配置时发生未知错误: {str(e)}"
            self.show_error("更新失败", error_msg)
            return False
        
    def setup_ui(self):
        """设置UI控件"""
        # 字体选择相关控件
        self.font_label = self.ui.findChild(QLabel, "FontLabel")
        self.choose_font_btn = self.ui.findChild(QPushButton, "ChooseFontBtn_2")
        self.reset_btn = self.ui.findChild(QPushButton, "ResetBtn")
        
        # 游戏路径相关控件
        self.path_edit = self.ui.findChild(QTextEdit, "Path")
        self.choose_path_btn = self.ui.findChild(QPushButton, "ChoosePathBtn")
        
        # 日志输出控件
        self.log_text = self.ui.findChild(QTextEdit, "logtext")
        
        # 功能按钮
        self.install_btn = self.ui.findChild(QPushButton, "InstallBtn")
        self.uninstall_btn = self.ui.findChild(QPushButton, "UninstallBtn")
        
        # 进度条
        self.progress_bar = self.ui.findChild(QProgressBar, "progressBar")
        
        # 初始化日志系统
        self.log_redirector = LogRedirector(self.log_text)
        sys.stdout = self.log_redirector
        sys.stderr = self.log_redirector
        self.logger = self.log_redirector.logger
        
    def setup_events(self):
        """设置事件处理"""
        # 字体选择相关事件
        self.choose_font_btn.clicked.connect(self.choose_font)
        self.reset_btn.clicked.connect(self.reset_font)
        
        # 游戏路径相关事件
        self.choose_path_btn.clicked.connect(self.choose_game_path)
        self.path_edit.textChanged.connect(self.on_path_changed)
        
        # 功能按钮事件
        self.install_btn.clicked.connect(self.start_installation)
        self.uninstall_btn.clicked.connect(self.uninstall)
        
    def load_path_record(self):
        """加载路径记录"""
        try:
            if os.path.exists('path-record.json'):
                with open('path-record.json', 'r', encoding='utf-8') as f:
                    paths = json.load(f)
                    
                    # 只处理非空的game_path
                    if paths.get('game_path'):
                        if self.validate_game_path(paths['game_path']):
                            self.game_path = paths['game_path']
                            self.path_edit.setText(self.game_path)
                        else:
                            self.show_error('错误', '保存的游戏目录已失效，请重新选择')
                    
                    # 只处理非空的font_path
                    if paths.get('font_path'):
                        if os.path.exists(paths['font_path']):
                            self.font_path = paths['font_path']
                            self.font_label.setText(f"选择的字体: {os.path.basename(self.font_path)}")
                        else:
                            self.show_error('提示', '保存的字体文件已不存在，请重新选择')
                            
        except Exception as e:
            self.logger.error(f'加载路径记录失败: {str(e)}')
            
    def save_path_record(self):
        """保存路径记录"""
        try:
            paths = {
                'game_path': self.game_path if self.game_path else '',
                'font_path': self.font_path if self.font_path else ''
            }
            with open('path-record.json', 'w', encoding='utf-8') as f:
                json.dump(paths, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.logger.error(f'保存路径记录失败: {str(e)}')
            
    def validate_game_path(self, path):
        """验证游戏目录"""
        return os.path.exists(os.path.join(path, 'LimbusCompany.exe'))
        
    def detect_steam_path(self):
        """检测Steam默认安装路径"""
        if self.game_path:  # 如果已经有游戏路径，就不需要检测
            return
            
        default_path = os.path.join('C:\\Program Files (x86)', 'Steam', 'steamapps', 'common', 'Limbus Company')
        if os.path.exists(default_path) and self.validate_game_path(default_path):
            result = QMessageBox.question(
                self.ui,
                '检测到游戏',
                '检测到Steam默认安装路径下的游戏，是否采用？\n注：如果是小白请直接点击确认即可',
                QMessageBox.Yes | QMessageBox.No
            )
            if result == QMessageBox.Yes:
                self.game_path = default_path
                self.path_edit.setText(self.game_path)
                self.save_path_record()
                
    def show_error(self, title, message):
        """显示错误信息"""
        QMessageBox.critical(self, title, message)
        self.logger.error(message)
        
    def show_info(self, title, message):
        """显示信息提示"""
        QMessageBox.information(self, title, message)
        self.logger.info(message)
        
    def choose_font(self):
        """选择字体文件"""
        font_path, _ = QFileDialog.getOpenFileName(
            self.ui,
            "选择字体文件",
            "",
            "字体文件 (*.ttf *.otf)"
        )
        if not font_path:
            self.font_path = "SourceHanSansCN-Normal.otf"
            self.font_label.setText("选择的字体: 思源黑体")
            self.save_path_record()
            self.logger.info("已选择默认字体: 思源黑体")
        else:
            self.font_path = font_path
            filename = os.path.basename(font_path)
            self.font_label.setText(f"选择的字体: {filename}")
            self.save_path_record()
            self.logger.info(f"已选择字体文件: {filename}")
            
    def reset_font(self):
        """重置字体选择"""
        self.font_path = "SourceHanSansCN-Normal.otf"
        self.font_label.setText("选择的字体: 思源黑体")
        self.save_path_record()
        self.logger.info("已重置字体选择")
        
    def choose_game_path(self):
        """选择游戏安装目录"""
        game_path = QFileDialog.getExistingDirectory(
            self.ui,
            "选择游戏目录",
            ""
        )
        if game_path:
            if self.validate_game_path(game_path):
                self.game_path = game_path
                self.path_edit.setText(game_path)
                self.save_path_record()
                self.logger.info(f"已选择游戏目录: {game_path}")
            else:
                self.show_error("错误", "选择的目录不是游戏根目录，请确保目录中包含LimbusCompany.exe")
                
    def on_path_changed(self):
        """游戏路径文本变更处理"""
        path = self.path_edit.toPlainText()
        if path and self.validate_game_path(path):
            self.game_path = path
            
    def uninstall(self):
        """卸载本地化内容"""
        if not self.game_path:
            self.logger.error("未选择游戏目录！")
            return
            
        self.logger.info("开始卸载本地化内容...")
        
        # 删除本地化文件夹
        target_path = os.path.join(self.game_path, "LimbusCompany_Data", "Lang", "LLC_CN")
        if os.path.exists(target_path):
            try:
                shutil.rmtree(target_path)
                self.logger.info("已删除本地化文件夹")
            except Exception as e:
                self.show_error("错误", f"删除本地化文件夹失败: {str(e)}")
                return
        
        # 删除配置文件
        json_target_path = os.path.join(self.game_path, "LimbusCompany_Data", "Lang", "config.json")
        if os.path.exists(json_target_path):
            try:
                os.remove(json_target_path)
                self.logger.info("已删除config.json")
            except Exception as e:
                self.show_error("错误", f"删除config.json失败: {str(e)}")
                return
        
        self.logger.info("卸载完成")
        self.show_info("卸载完成", "本地化内容已成功卸载！")
        
    def start_installation(self):
        """开始安装过程"""
        if self._is_downloading:
            self.stop_installation()
            return
            
        if not self.game_path:
            self.show_error("错误", "未选择游戏目录！")
            return
            
        # 下载安装配置
        if not self.download_install_config():
            return
            
        # 检查并清理临时目录
        temp_dir = os.path.join(os.getcwd(), "temp_extract")
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                self.logger.info("已清理旧的临时目录")
            except Exception as e:
                self.show_error("错误", f"清理临时目录失败: {str(e)}")
                return
            
        self.logger.info("开始安装...")
        self._is_downloading = True
        self.install_btn.setText("停止")
        self.progress_bar.setValue(0)
        
        # 启动下载线程
        url = self.install_config.get('link')
        file_name = self.install_config.get('file')
        save_path = os.path.join(os.getcwd(), file_name)
        
        self.download_thread = DownloadThread(url, save_path, self.logger)
        self.download_thread.progress_updated.connect(self.update_progress)
        self.download_thread.download_finished.connect(self.on_download_finished)
        self.download_thread.download_error.connect(self.on_download_error)
        self.download_thread.start()
        
    def stop_installation(self):
        """停止安装过程"""
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.stop()
            self.download_thread.wait()
            
        self._is_downloading = False
        self.install_btn.setText("安装")
        self.logger.info("下载已停止")
        
    def on_download_finished(self, file_path):
        """下载完成处理"""
        self._is_downloading = False
        self.install_btn.setText("安装")
        self.logger.info(f"文件下载完成: {file_path}")
        self.post_download_operations(file_path)
        
    def on_download_error(self, error_msg):
        """下载错误处理"""
        self._is_downloading = False
        self.install_btn.setText("安装")
        self.show_error("下载错误", error_msg)
        
    def update_progress(self, progress):
        """更新进度条"""
        with QMutexLocker(self._ui_mutex):
            self.progress_bar.setValue(progress)
            
    def post_download_operations(self, archive_path):
        """下载后处理操作"""
        try:
            target_path = os.path.join(self.game_path, "LimbusCompany_Data", "Lang", "LLC_CN")
            
            # 创建目标目录
            if not os.path.exists(target_path):
                os.makedirs(target_path)
                
            # 解压资源文件
            self.logger.info("开始解压资源文件...")
            archive_type = self.install_config.get('type', 'zip')
            
            if archive_type == 'zip':
                import zipfile
                with zipfile.ZipFile(archive_path, 'r') as archive:
                    # 先提取所有文件到临时目录
                    temp_dir = os.path.join(os.getcwd(), "temp_extract")
                    archive.extractall(path=temp_dir)
            elif archive_type == '7z':
                with py7zr.SevenZipFile(archive_path, mode='r') as archive:
                    # 先提取所有文件到临时目录
                    temp_dir = os.path.join(os.getcwd(), "temp_extract")
                    archive.extractall(path=temp_dir)
            else:
                raise Exception(f"不支持的压缩包格式: {archive_type}")
                
            # 找到源目录
            absolute_path = self.install_config.get('absolutePath', '')
            source_path = os.path.join(temp_dir, *absolute_path.split('/'))
            
            if os.path.exists(source_path):
                # 复制文件到目标目录
                for root, dirs, files in os.walk(source_path):
                    relative_path = os.path.relpath(root, source_path)
                    target_dir = os.path.join(target_path, relative_path)
                    
                    if not os.path.exists(target_dir):
                        os.makedirs(target_dir)
                        
                    for file in files:
                        src_file = os.path.join(root, file)
                        dst_file = os.path.join(target_dir, file)
                        shutil.copy2(src_file, dst_file)
                
                self.logger.info("资源文件解压完成")
            else:
                raise Exception("压缩包中找不到预期的目录结构")
                
                # 清理临时目录
                shutil.rmtree(temp_dir)
            
            # 更新配置文件
            json_data = {"lang": "LLC_CN"}
            json_target_path = os.path.join(self.game_path, "LimbusCompany_Data", "Lang", "config.json")
            
            if os.path.exists(json_target_path):
                with open(json_target_path, 'r', encoding='utf-8') as json_file:
                    json_data_exist = json.load(json_file)
                if json_data_exist != json_data:
                    with open(json_target_path, 'w', encoding='utf-8') as json_file:
                        json.dump(json_data, json_file, ensure_ascii=False, indent=4)
                    self.logger.info("已更新config.json配置")
            else:
                with open(json_target_path, 'w', encoding='utf-8') as json_file:
                    json.dump(json_data, json_file, ensure_ascii=False, indent=4)
                self.logger.info("已创建config.json配置文件")
            
            # 处理字体文件
            if self.font_path and self.font_path != "SourceHanSansCN-Normal.otf":
                font_target_path = os.path.join(target_path, "Font")
                if os.path.exists(font_target_path):
                    shutil.rmtree(font_target_path)
                os.makedirs(font_target_path)
                shutil.copy2(self.font_path, font_target_path)
                self.logger.info("已复制字体文件到游戏目录")
            else:
                self.logger.info("未设置字体文件或使用默认字体，跳过字体安装")
                
            self.logger.info("安装完成！")
            self.show_info("安装完成", "本地化内容已成功安装！")
            
        except Exception as e:
            self.show_error("错误", f"安装过程中发生错误: {str(e)}")
        finally:
            # 清理临时文件和目录
            try:
                if os.path.exists(archive_path):
                    os.remove(archive_path)
                    self.logger.info("已清理下载的压缩文件")
                temp_dir = os.path.join(os.getcwd(), "temp_extract")
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    self.logger.info("已清理临时目录")
            except Exception as e:
                self.logger.error(f"清理临时文件失败: {str(e)}")
            finally:
                self._is_downloading = False
                self.install_btn.setText("安装")

class LogRedirector:
    """日志重定向器"""
    
    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.setup_logger()
        
    def setup_logger(self):
        """配置日志记录器"""
        self.logger = logging.getLogger('LLC-TR')
        self.logger.setLevel(logging.DEBUG)
        handler = LoggingHandler(self)
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
    def write(self, text):
        """写入日志文本"""
        if text.strip():
            self.logger.info(text.rstrip())
            
    def flush(self):
        """刷新缓冲区"""
        pass
        
    def append_text(self, text):
        """追加文本到日志窗口"""
        cursor = self.text_widget.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text + '\n')
        self.text_widget.setTextCursor(cursor)
        self.text_widget.ensureCursorVisible()

class LoggingHandler(logging.Handler):
    """日志处理器"""
    
    def __init__(self, redirector):
        super().__init__()
        self.redirector = redirector
        
    def emit(self, record):
        """发送日志记录"""
        msg = self.format(record)
        self.redirector.append_text(msg)


def main():
    """程序入口函数"""
    app = QApplication(sys.argv)
    window = MainWindow()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()