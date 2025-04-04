import sys
import os
import zipfile
from PySide6 import QtUiTools, QtCore
from PySide6.QtWidgets import QApplication, QMainWindow

class InstallerApp(QMainWindow):
    progress_signal = QtCore.Signal(int)
    log_signal = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        ui_path = getattr(sys, '_MEIPASS', os.getcwd())
        ui_file = os.path.join(ui_path, 'llc-installer.ui')
        self.ui = QtUiTools.QUiLoader().load(ui_file)
        self.setCentralWidget(self.ui)
        self.progressBar = self.ui.progressBar
        self.textEdit = self.ui.textEdit
        self.progressBar.setValue(0)
        self.textEdit.clear()
        self.progress_signal.connect(self.update_progress)
        self.log_signal.connect(self.update_log)
        self.start_unzip()

    def update_progress(self, value):
        self.progressBar.setValue(value)

    def update_log(self, text):
        self.textEdit.append(text)

    def start_unzip(self):
        self.worker = UnzipWorker()
        self.worker.progress_signal.connect(self.progress_signal.emit)
        self.worker.log_signal.connect(self.log_signal.emit)
        self.worker.finished.connect(self.launch_app)
        self.worker.start()

    def launch_app(self):
        exe_path = os.path.join(os.getcwd(), 'LocalizeLimbusCompany-TR', 'LocalizeLimbusCompany-TR.exe')
        if os.path.exists(exe_path):
            os.startfile(exe_path)
            QApplication.quit()
        else:
            self.log_signal.emit('错误：未找到LocalizeLimbusCompany-TR.exe文件')

class UnzipWorker(QtCore.QThread):
    progress_signal = QtCore.Signal(int)
    log_signal = QtCore.Signal(str)

    def run(self):
        zip_path = os.path.join(getattr(sys, '_MEIPASS', os.getcwd()), 'LocalizeLimbusCompany-TR.zip')
        if not os.path.exists(zip_path):
            self.log_signal.emit('错误：未找到LocalizeLimbusCompany-TR.zip文件')
            return

        output_dir = os.path.join(os.getcwd(), 'LocalizeLimbusCompany-TR')
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                total_files = len(zip_ref.namelist())
                for i, file in enumerate(zip_ref.namelist()):
                    self.log_signal.emit(f'正在解压：{file}')
                    zip_ref.extract(file, output_dir)
                    progress = int((i + 1) / total_files * 100)
                    self.progress_signal.emit(progress)

            self.log_signal.emit('解压完成！')
            self.progress_signal.emit(100)
        except Exception as e:
            self.log_signal.emit(f'解压错误：{str(e)}')


if __name__ == '__main__':
    app = QApplication(sys.argv)
    installer = InstallerApp()
    installer.show()
    sys.exit(app.exec_())