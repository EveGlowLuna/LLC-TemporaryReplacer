import sys
import os
import zipfile
from PySide6 import QtUiTools
from PySide6.QtWidgets import QApplication, QMainWindow

class InstallerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        ui_path = getattr(sys, '_MEIPASS', os.getcwd())
        ui_file = os.path.join(ui_path, 'llc-installer.ui')
        QtUiTools.QUiLoader().load(ui_file, self)
        self.progressBar.setValue(0)
        self.textEdit.clear()
        self.start_unzip()

    def start_unzip(self):
        zip_path = os.path.join(os.getcwd(), 'LocalizeLimbusCompany-TR.zip')
        if not os.path.exists(zip_path):
            self.textEdit.append('错误：未找到LocalizeLimbusCompany-TR.zip文件')
            return

        output_dir = os.path.join(os.getcwd(), 'LocalizeLimbusCompany-TR')
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                total_files = len(zip_ref.namelist())
                for i, file in enumerate(zip_ref.namelist()):
                    self.textEdit.append(f'正在解压：{file}')
                    zip_ref.extract(file, output_dir)
                    progress = int((i + 1) / total_files * 100)
                    self.progressBar.setValue(progress)
                    QApplication.processEvents()

            self.textEdit.append('解压完成！')
            self.progressBar.setValue(100)
            self.launch_app()
        except Exception as e:
            self.textEdit.append(f'解压错误：{str(e)}')

    def launch_app(self):
        exe_path = os.path.join(os.getcwd(), 'LocalizeLimbusCompany-TR', 'LocalizeLimbusCompany-TR.exe')
        if os.path.exists(exe_path):
            os.startfile(exe_path)
            sys.exit()
        else:
            self.textEdit.append('错误：未找到LocalizeLimbusCompany-TR.exe文件')

if __name__ == '__main__':
    app = QApplication(sys.argv)
    installer = InstallerApp()
    installer.show()
    sys.exit(app.exec_())