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
"""

import sys
import os
import json
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog,
    QPushButton, QLabel, QTextEdit, QProgressBar,
    QMessageBox, QCheckBox
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
    提供了重试机制和备用URL支持，增强下载稳定性。
    
    信号:
        progress_updated: 下载进度更新信号
        download_finished: 下载完成信号
        download_error: 下载错误信号
    """
    
    progress_updated = Signal(int)
    download_finished = Signal(str)
    download_error = Signal(str)
    
    def __init__(self, url, save_path, logger, backup_url=None):
        """初始化下载线程
        
        Args:
            url: 下载文件的URL
            save_path: 保存路径
            logger: 日志记录器实例
            backup_url: 备用下载URL，当主URL失败时使用
        """
        super().__init__()
        self.url = url
        self.backup_url = backup_url
        self.save_path = save_path
        self.logger = logger
        self._stop_flag = False
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        self.max_retries = 3  # 最大重试次数
        
    def stop(self):
        """停止下载
        
        设置停止标志并唤醒等待中的线程。
        """
        with QMutexLocker(self._mutex):
            self._stop_flag = True
            self._condition.wakeAll()
        
    def run(self):
        """执行下载操作
        
        使用requests库下载文件，支持进度回调和取消操作。
        实现了重试机制和备用URL切换，提高下载成功率。
        """
        retry_count = 0
        retry_delay = 2  # 重试间隔秒数
        current_url = self.url
        used_backup = False
        
        while retry_count < self.max_retries:
            try:
                # 检查是否需要切换到备用URL
                if retry_count > 0 and self.backup_url and not used_backup:
                    current_url = self.backup_url
                    self.logger.info(f"切换到备用下载链接: jsdelivr.net")
                    used_backup = True
                
                # 设置请求头，模拟浏览器行为
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                
                # 设置超时
                response = requests.get(
                    current_url, 
                    stream=True, 
                    timeout=(5, 60),  # 连接超时5秒，读取超时60秒
                    headers=headers
                )
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
                return  # 下载成功，退出循环
                
            except requests.exceptions.Timeout as e:
                retry_count += 1
                if retry_count >= self.max_retries:
                    error_msg = f"下载超时，请检查网络连接: {str(e)}"
                    self.logger.error(error_msg)
                    self.download_error.emit(error_msg)
                    return
                self.logger.warning(f"下载超时，{retry_delay}秒后重试...({retry_count}/{self.max_retries})")
                import time
                time.sleep(retry_delay)
                
            except requests.exceptions.ConnectionError as e:
                retry_count += 1
                if retry_count >= self.max_retries:
                    error_msg = f"网络连接错误: {str(e)}"
                    self.logger.error(error_msg)
                    self.download_error.emit(error_msg)
                    return
                self.logger.warning(f"连接错误，{retry_delay}秒后重试...({retry_count}/{self.max_retries})")
                import time
                time.sleep(retry_delay)
                
            except requests.RequestException as e:
                error_msg = f"下载失败: {str(e)}"
                self.logger.error(error_msg)
                self.download_error.emit(error_msg)
                return

class MainWindow(QMainWindow):
    """主窗口类
    
    负责处理UI初始化、事件绑定和主要业务逻辑的实现。
    提供完整的本地化工具功能，包括字体选择、游戏路径设置、安装和卸载功能。
    """
    
    def __init__(self):
        """初始化主窗口
        
        设置UI界面、初始化变量、绑定事件处理函数，并尝试加载已保存的配置。
        """
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
        """初始化UI界面
        
        加载UI文件并创建主界面，处理不同环境下的路径差异。
        """
        # 获取UI文件的路径
        if getattr(sys, 'frozen', False):
            # 如果是打包后的可执行文件
            self.base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        else:
            # 如果是开发环境
            self.base_path = os.path.dirname(os.path.abspath(__file__))
            
        # 加载主界面
        ui_path = os.path.join(self.base_path, "llc-tr-ui.ui")
        ui_file = QFile(ui_path)
        
        if not ui_file.open(QIODevice.OpenModeFlag.ReadOnly):
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
        """初始化成员变量
        
        设置程序运行所需的各种状态变量和配置变量的初始值。
        """
        self.game_path = ""
        self.name = ""
        self.download_thread = None
        self._is_downloading = False
        self.install_config = None
        self.use_mirror = False
        self.font_path = "" # 初始化font_path
        self.custom_proxy_url = "" # 初始化自定义代理URL
        
    def setup_ui(self):
        """设置UI控件
        
        查找并初始化界面上的各个控件，设置日志系统。
        """
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
        
        # 镜像站设置
        self.use_mirror_checkbox = self.ui.findChild(QCheckBox, "use_mirror")
        
        # 初始化日志系统
        self.log_redirector = LogRedirector(self.log_text)
        sys.stdout = self.log_redirector
        sys.stderr = self.log_redirector
        self.logger = self.log_redirector.logger
        
    def setup_events(self):
        """设置事件处理
        
        将UI控件的事件与相应的处理函数绑定。
        """
        # 字体选择相关事件
        self.choose_font_btn.clicked.connect(self.choose_font)
        self.reset_btn.clicked.connect(self.reset_font)
        
        # 游戏路径相关事件
        self.choose_path_btn.clicked.connect(self.choose_game_path)
        self.path_edit.textChanged.connect(self.on_path_changed)
        
        # 功能按钮事件
        self.install_btn.clicked.connect(self.start_installation)
        self.uninstall_btn.clicked.connect(self.uninstall)
        
        # 镜像站设置事件
        self.use_mirror_checkbox.stateChanged.connect(self.on_mirror_changed)
        
    def load_path_record(self):
        """加载配置文件
        
        从config.json文件中加载配置信息，包括游戏路径、字体路径和镜像站设置。
        如果配置文件不存在或读取失败，将使用默认设置。
        """
        try:
            if os.path.exists('config.json'):
                with open('config.json', 'r', encoding='utf-8') as f:
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
                    
                    # 加载镜像站配置
                    if 'use-mirror' in paths:
                        self.use_mirror = paths['use-mirror']
                        self.use_mirror_checkbox.setChecked(self.use_mirror)
                    
                    # 加载自定义代理URL
                    if 'custom-proxy-url' in paths:
                        self.custom_proxy_url = paths['custom-proxy-url']
                        # 假设有一个QTextEdit或QLineEdit用于显示和编辑自定义代理URL
                        # self.custom_proxy_edit.setText(self.custom_proxy_url) # 这部分UI修改将在下一步进行
                            
        except Exception as e:
            self.logger.error(f'加载配置文件失败: {str(e)}')
            
    def save_path_record(self):
        """保存配置文件
        
        将当前的配置信息保存到config.json文件中，包括游戏路径、字体路径和镜像站设置。
        """
        try:
            paths = {
                'game_path': self.game_path if self.game_path else '',
                'font_path': self.font_path if self.font_path else '',
                'use-mirror': self.use_mirror,
                'custom-proxy-url': self.custom_proxy_url if self.custom_proxy_url else ''
            }
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(paths, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.logger.error(f'保存配置文件失败: {str(e)}')
            
    def validate_game_path(self, path):
        """验证游戏目录
        
        检查指定路径是否为有效的游戏安装目录，通过查找LimbusCompany.exe文件来验证。
        
        Args:
            path: 要验证的游戏目录路径
            
        Returns:
            bool: 如果是有效的游戏目录返回True，否则返回False
        """
        return os.path.exists(os.path.join(path, 'LimbusCompany.exe'))
        
    def detect_steam_path(self):
        """检测Steam默认安装路径
        
        自动检测Steam默认安装路径下的游戏目录，如果找到则提示用户是否使用该路径。
        仅在未设置游戏路径时执行检测。
        """
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
        """显示错误信息
        
        显示错误对话框并记录错误日志。
        
        Args:
            title: 错误对话框标题
            message: 错误信息内容
        """
        QMessageBox.critical(self, title, message)
        self.logger.error(message)
        
    def show_info(self, title, message):
        """显示信息提示
        
        显示信息对话框并记录信息日志。
        
        Args:
            title: 信息对话框标题
            message: 信息内容
        """
        QMessageBox.information(self, title, message)
        self.logger.info(message)
        
    def choose_font(self):
        """选择字体文件
        
        打开文件选择对话框，让用户选择自定义字体文件(.ttf或.otf)。
        选择后更新界面显示并保存配置。
        """
        font_path, _ = QFileDialog.getOpenFileName(
            self.ui,
            "选择字体文件",
            "",
            "字体文件 (*.ttf *.otf)"
        )
        if not font_path:
            self.font_path = ""
            self.font_label.setText("未选择字体")
            self.save_path_record()
            self.logger.info("未选择字体")
        else:
            self.font_path = font_path
            filename = os.path.basename(font_path)
            self.font_label.setText(f"选择的字体: {filename}")
            self.save_path_record()
            self.logger.info(f"已选择字体文件: {filename}")
            
    def reset_font(self):
        """重置字体选择
        
        清除当前选择的字体，恢复到默认状态。
        """
        self.font_path = ""
        self.font_label.setText("未选择字体")
        self.save_path_record()
        self.logger.info("已重置字体选择")
        
    def choose_game_path(self):
        """选择游戏安装目录
        
        打开目录选择对话框，让用户选择游戏安装目录。
        选择后会验证目录有效性，更新界面显示并保存配置。
        """
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
        """游戏路径文本变更处理
        
        当用户在文本框中手动编辑游戏路径时，验证并更新游戏路径设置。
        """
        path = self.path_edit.toPlainText()
        if path and self.validate_game_path(path):
            self.game_path = path
            
    def on_mirror_changed(self, state):
        """镜像站设置变更处理
        
        当用户切换镜像站设置时，更新配置并保存。
        
        Args:
            state: 复选框状态值，Qt.Checked=2表示选中
        """
        self.use_mirror = (state == 2)  # Qt.Checked = 2
        self.logger.info(f"镜像站设置已{'启用' if self.use_mirror else '禁用'}")
        self.save_path_record()
            
    def uninstall(self, show_message=True):
        """卸载本地化内容
        
        移除游戏目录中的本地化文件和配置，恢复游戏到原始状态。
        包括删除本地化文件夹和配置文件。
        
        Args:
            show_message: 是否显示卸载完成的提示信息，默认为True
            
        Returns:
            bool: 卸载成功返回True，失败返回False
        """
        if not self.game_path:
            self.logger.error("未选择游戏目录！")
            return False
            
        self.logger.info("开始卸载本地化内容...")
        
        # 删除本地化文件夹
        target_path = os.path.join(self.game_path, "LimbusCompany_Data", "Lang", self.name)
        if os.path.exists(target_path):
            try:
                shutil.rmtree(target_path)
                self.logger.info("已删除本地化文件夹")
            except Exception as e:
                self.show_error("错误", f"删除本地化文件夹失败: {str(e)}")
                return False
        
        # 删除配置文件
        json_target_path = os.path.join(self.game_path, "LimbusCompany_Data", "Lang", "config.json")
        if os.path.exists(json_target_path):
            try:
                os.remove(json_target_path)
                self.logger.info("已删除配置文件")
            except Exception as e:
                if show_message:
                    self.show_error("错误", f"删除配置文件失败: {str(e)}")
                return False
                
        self.logger.info("卸载完成")
        if show_message:
            self.show_info("成功", "本地化内容已成功卸载！")
        return True
        
    def download_install_config(self):
        """下载安装配置文件
        
        从GitHub仓库获取最新的安装配置信息，使用jsdelivr镜像站加速下载。
        
        Returns:
            bool: 下载成功返回True，失败返回False
        """
        max_retries = 3  # 最大重试次数
        retry_count = 0
        retry_delay = 2  # 重试间隔秒数
        
        while retry_count < max_retries:
            try:
                self.logger.info(f"正在获取最新安装配置信息...{'' if retry_count == 0 else f'(第{retry_count+1}次尝试)'}")
                github_raw_url = "https://raw.githubusercontent.com/EveGlowLuna/LLC-TemporaryReplacer/refs/heads/main/install_info.json"
                config_url = github_raw_url

                if self.use_mirror:
                    if self.custom_proxy_url:
                        # 使用用户自定义代理
                        parsed_github_url = urlparse(github_raw_url)
                        # 确保自定义代理URL以'/'结尾，如果不是，则添加
                        base_proxy_url = self.custom_proxy_url.rstrip('/')
                        # 拼接代理URL和GitHub路径
                        config_url = f"{base_proxy_url}/{parsed_github_url.netloc}{parsed_github_url.path}"
                        self.logger.info(f"使用自定义代理下载配置: {config_url}")
                    else:
                        # 使用默认镜像站
                        config_url = "https://gh-proxy.com/raw.githubusercontent.com/EveGlowLuna/LLC-TemporaryReplacer/refs/heads/main/install_info.json"
                        self.logger.info("使用默认镜像站下载配置。")
                else:
                    self.logger.info("不使用镜像站，直接从GitHub下载配置。")
                
                # 增加超时时间，connect=5秒，read=30秒
                response = requests.get(
                    config_url, 
                    timeout=(5, 30),
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                )
                response.raise_for_status()
                try:
                    self.install_config = response.json()
                except json.JSONDecodeError as e:
                    error_msg = f"安装配置文件格式错误: {str(e)}"
                    self.logger.error(error_msg)
                    self.show_error("更新失败", error_msg)
                    return False
                self.name = self.install_config.get('name', 'LLC-zh-CN')
                if not self.name:
                    self.name = 'LLC-zh-CN'  # 设置默认值
                self.logger.info(f"成功获取安装配置信息，本地化名称: {self.name}")
                return True
                
            except requests.exceptions.Timeout as e:
                retry_count += 1
                if retry_count >= max_retries:
                    error_msg = "获取安装配置超时，请检查网络连接"
                    self.logger.error(f"超时错误: {str(e)}")
                    self.show_error("更新失败", error_msg)
                    return False
                self.logger.warning(f"请求超时，{retry_delay}秒后重试...({retry_count}/{max_retries})")
                import time
                time.sleep(retry_delay)
                
            except requests.exceptions.ConnectionError as e:
                retry_count += 1
                if retry_count >= max_retries:
                    error_msg = "网络连接错误，无法获取安装配置"
                    self.logger.error(f"连接错误: {str(e)}")
                    self.show_error("更新失败", error_msg)
                    return False
                self.logger.warning(f"连接错误，{retry_delay}秒后重试...({retry_count}/{max_retries})")
                import time
                time.sleep(retry_delay)
                
            except requests.RequestException as e:
                error_msg = f"获取安装配置时发生错误: {str(e)}"
                self.logger.error(error_msg)
                self.show_error("更新失败", error_msg)
                return False
                
            except json.JSONDecodeError as e:
                error_msg = "安装配置文件格式错误"
                self.logger.error(f"JSON解析错误: {str(e)}")
                self.show_error("更新失败", error_msg)
                return False
                
            except Exception as e:
                error_msg = f"获取安装配置时发生未知错误: {str(e)}"
                self.logger.error(error_msg)
                self.show_error("更新失败", error_msg)
                return False
                
        
    def start_installation(self):
        """开始安装过程
        
        根据用户选择的版本类型执行相应的安装流程。
        首先执行卸载操作，然后根据版本类型执行安装。
        """
        if self._is_downloading:
            self.stop_installation()
            return
            
        if not self.game_path:
            self.show_error("错误", "未选择游戏目录！")
            return

        # 先执行卸载操作
        if not self.uninstall(False):
            return
        
        # 下载安装配置
        if not self.download_install_config():
            return
                
                
        self.logger.info("开始安装...")
        self._is_downloading = True
        self.install_btn.setText("停止")
        self.progress_bar.setValue(0)
            
        # 启动下载线程
        url = self.install_config.get('content-link')

        # 从URL提取文件名
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        file_name = os.path.basename(parsed_url.path)
        if not file_name:
            file_name = 'LimbusLocalize_latest.7z'  # 默认文件名

        save_path = os.path.join(os.getcwd(), file_name)

            
        # 下载资源包
        self.download_thread = DownloadThread(url, save_path, self.logger)
        self.download_thread.progress_updated.connect(self.update_progress)
        self.download_thread.download_finished.connect(self.on_download_finished)
        self.download_thread.download_error.connect(self.on_download_error)
        self.download_thread.start()

        # 下载字体包
        font_url = self.install_config.get('font-link')
        if font_url:
            # 从URL提取字体文件名
            from urllib.parse import urlparse
            parsed_font_url = urlparse(font_url)
            font_file_name = os.path.basename(parsed_font_url.path)
            if not font_file_name:
                font_file_name = 'LLCCN-Font.7z'  # 默认文件名

            font_save_path = os.path.join(os.getcwd(), font_file_name)
            self.font_download_thread = DownloadThread(font_url, font_save_path, self.logger)
            self.font_download_thread.progress_updated.connect(self.update_progress)
            self.font_download_thread.download_finished.connect(self.on_font_download_finished)
            self.font_download_thread.download_error.connect(self.on_download_error)
            self.font_download_thread.start()
        
    def stop_installation(self):
        """停止安装过程"""
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.stop()
            self.download_thread.wait()
            
        self._is_downloading = False
        self.install_btn.setText("安装")
        self.logger.info("下载已停止")
        
    def on_download_finished(self, file_path):
        # 检查文件是否为字体文件
        font_url = self.install_config.get('font-link')
        if font_url:
            from urllib.parse import urlparse
            parsed_font_url = urlparse(font_url)
            expected_font_file = os.path.basename(parsed_font_url.path)
            if expected_font_file and file_path.endswith(expected_font_file):
                self.on_font_download_finished(file_path)
                return
        """下载完成处理"""
        self._is_downloading = False
        self.install_btn.setText("安装")
        self.logger.info(f"文件下载完成: {file_path}")
        self.post_download_operations(file_path)
        
    def on_font_download_finished(self, font_path):
        try:
            # 定义目标目录
            target_dir = self.game_path

            # 确保游戏目录存在
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)

            # 直接解压字体文件到游戏根目录
            archive_type = self.install_config.get('font-type', '7z')
            if archive_type == '7z':
                seven_zip_exe = os.path.join(self.base_path, "tool", "7z.exe")
                command = [seven_zip_exe, 'x', font_path, f'-o{target_dir}', '-y']
                self.logger.info("开始直接解压字体文件到目标目录...")
                
                process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
                # 将7z的输出以DEBUG级别记录到终端
                print(f"\n[DEBUG] 7z output:\n{process.stdout}", file=sys.__stdout__)
                
                if process.returncode != 0:
                    raise Exception(f"7z解压失败: {process.stderr}")
                self.logger.info("字体文件解压完成")
            
            self.logger.info("字体安装完成")
        except Exception as e:
            self.show_error("错误", f"字体安装过程中发生错误: {str(e)}")
        finally:
            if os.path.exists(font_path):
                os.remove(font_path)
                self.logger.info("已清理下载的字体压缩文件")

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
        # 检查是否为字体文件
        font_url = self.install_config.get('font-link')
        if font_url:
            from urllib.parse import urlparse
            parsed_font_url = urlparse(font_url)
            expected_font_file = os.path.basename(parsed_font_url.path)
            if expected_font_file and archive_path.endswith(expected_font_file):
                self.logger.info("字体文件下载完成，开始解压...")
                self.extract_font(archive_path)
                return
        """下载后处理操作"""
        try:
            # 解压资源文件
            self.logger.info("开始解压资源文件...")
            archive_type = self.install_config.get('content-type', 'zip')

            # 直接解压到游戏目录
            target_dir = self.game_path
            # 确保游戏目录存在
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)

            if archive_type == 'zip':
                import zipfile
                with zipfile.ZipFile(archive_path, 'r') as archive:
                    archive.extractall(path=target_dir)
            elif archive_type == '7z':
                # 使用7z.exe解压
                seven_zip_exe = os.path.join(self.base_path, "tool", "7z.exe")
                if not os.path.exists(seven_zip_exe):
                    raise Exception(f"7z.exe not found at {seven_zip_exe}")

                command = [seven_zip_exe, 'x', archive_path, f'-o{target_dir}', '-y']
                self.logger.info(f"执行解压命令: {' '.join(command)}")

                import subprocess
                process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')

                if process.returncode != 0:
                    self.logger.error(f"7z解压失败: {process.stderr}")
                    raise Exception(f"7z解压失败: {process.stderr}")
                else:
                    self.logger.info("7z解压成功")
                    self.logger.debug(process.stdout)
            else:
                raise Exception(f"不支持的压缩包格式: {archive_type}")

            self.logger.info("资源文件解压完成")

            # 处理字体文件
            if self.font_path and self.font_path != "SourceHanSansCN-Normal.otf":
                font_target_path = os.path.join(self.game_path, "LimbusCompany_Data", "Lang", "LLC_zh-CN", "Font")
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
            # 清理临时文件
            try:
                if os.path.exists(archive_path):
                    os.remove(archive_path)
                    self.logger.info("已清理下载的压缩文件")
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
        # 同时输出到UI和终端
        self.redirector.append_text(msg)
        print(msg, file=sys.__stdout__)


def main():
    """程序入口函数"""
    app = QApplication(sys.argv)
    window = MainWindow()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()