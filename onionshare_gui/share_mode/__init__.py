# -*- coding: utf-8 -*-
"""
OnionShare | https://onionshare.org/

Copyright (C) 2014-2018 Micah Lee <micah@micahflee.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import threading
import os
from PyQt5 import QtCore, QtWidgets, QtGui

from onionshare import strings
from onionshare.onion import *
from onionshare.common import Common
from onionshare.web import Web

from .file_selection import FileSelection
from .downloads import Downloads
from ..mode import Mode
from ..widgets import Alert

class ShareMode(Mode):
    """
    Parts of the main window UI for sharing files.
    """
    def init(self):
        """
        Custom initialization for ReceiveMode.
        """
        # Create the Web object
        self.web = Web(self.common, True, False)

        # File selection
        self.file_selection = FileSelection(self.common)
        if self.filenames:
            for filename in self.filenames:
                self.file_selection.file_list.add_file(filename)
        
        # Server status
        self.server_status.set_mode('share', self.file_selection)
        self.server_status.server_started.connect(self.file_selection.server_started)
        self.server_status.server_stopped.connect(self.file_selection.server_stopped)
        self.server_status.server_stopped.connect(self.update_primary_action)
        self.server_status.server_canceled.connect(self.file_selection.server_stopped)
        self.server_status.server_canceled.connect(self.update_primary_action)
        self.file_selection.file_list.files_updated.connect(self.server_status.update)
        self.file_selection.file_list.files_updated.connect(self.update_primary_action)
        # Tell server_status about web, then update
        self.server_status.web = self.web
        self.server_status.update()

        # Filesize warning
        self.filesize_warning = QtWidgets.QLabel()
        self.filesize_warning.setWordWrap(True)
        self.filesize_warning.setStyleSheet('padding: 10px 0; font-weight: bold; color: #333333;')
        self.filesize_warning.hide()

        # Downloads
        self.downloads = Downloads(self.common)
        self.downloads_in_progress = 0
        self.downloads_completed = 0
        self.new_download = False # For scrolling to the bottom of the downloads list

        # Info label along top of screen
        self.info_layout = QtWidgets.QHBoxLayout()
        self.info_label = QtWidgets.QLabel()
        self.info_label.setStyleSheet('QLabel { font-size: 12px; color: #666666; }')

        self.info_show_downloads = QtWidgets.QToolButton()
        self.info_show_downloads.setIcon(QtGui.QIcon(self.common.get_resource_path('images/download_window_gray.png')))
        self.info_show_downloads.setCheckable(True)
        self.info_show_downloads.toggled.connect(self.downloads_toggled)
        self.info_show_downloads.setToolTip(strings._('gui_downloads_window_tooltip', True))

        self.info_in_progress_downloads_count = QtWidgets.QLabel()
        self.info_in_progress_downloads_count.setStyleSheet('QLabel { font-size: 12px; color: #666666; }')

        self.info_completed_downloads_count = QtWidgets.QLabel()
        self.info_completed_downloads_count.setStyleSheet('QLabel { font-size: 12px; color: #666666; }')

        self.update_downloads_completed(self.downloads_in_progress)
        self.update_downloads_in_progress(self.downloads_in_progress)

        self.info_layout.addWidget(self.info_label)
        self.info_layout.addStretch()
        self.info_layout.addWidget(self.info_in_progress_downloads_count)
        self.info_layout.addWidget(self.info_completed_downloads_count)
        self.info_layout.addWidget(self.info_show_downloads)

        self.info_widget = QtWidgets.QWidget()
        self.info_widget.setLayout(self.info_layout)
        self.info_widget.hide()

        # Primary action layout
        self.primary_action_layout.addWidget(self.filesize_warning)
        self.primary_action.hide()
        self.update_primary_action()

        # Status bar, zip progress bar
        self._zip_progress_bar = None

        # Layout
        self.layout.insertLayout(0, self.file_selection)
        self.layout.insertWidget(0, self.info_widget)

        # Always start with focus on file selection
        self.file_selection.setFocus()

    def timer_callback_custom(self):
        """
        This method is called regularly on a timer while share mode is active.
        """
        # Scroll to the bottom of the download progress bar log pane if a new download has been added
        if self.new_download:
            self.downloads.downloads_container.vbar.setValue(self.downloads.downloads_container.vbar.maximum())
            self.new_download = False
    
    def get_stop_server_shutdown_timeout_text(self):
        """
        Return the string to put on the stop server button, if there's a shutdown timeout
        """
        return strings._('gui_share_stop_server_shutdown_timeout', True)
    
    def timeout_finished_should_stop_server(self):
        """
        The shutdown timer expired, should we stop the server? Returns a bool
        """
        # If there were no attempts to download the share, or all downloads are done, we can stop
        if self.web.download_count == 0 or self.web.done:
            self.server_status.stop_server()
            self.server_status_label.setText(strings._('close_on_timeout', True))
            return True
        # A download is probably still running - hold off on stopping the share
        else:
            self.server_status_label.setText(strings._('timeout_download_still_running', True))
            return False

    def start_server_custom(self):
        """
        Starting the server.
        """
        # Reset web counters
        self.web.download_count = 0
        self.web.error404_count = 0
        
        # Hide and reset the downloads if we have previously shared
        self.downloads.reset_downloads()
        self.reset_info_counters()
    
    def start_server_step2_custom(self):
        """
        Step 2 in starting the server. Zipping up files.
        """
        # Add progress bar to the status bar, indicating the compressing of files.
        self._zip_progress_bar = ZipProgressBar(0)
        self.filenames = []
        for index in range(self.file_selection.file_list.count()):
            self.filenames.append(self.file_selection.file_list.item(index).filename)

        self._zip_progress_bar.total_files_size = ShareMode._compute_total_size(self.filenames)
        self.status_bar.insertWidget(0, self._zip_progress_bar)

        # Prepare the files for sending in a new thread
        def finish_starting_server(self):
            # Prepare files to share
            def _set_processed_size(x):
                if self._zip_progress_bar != None:
                    self._zip_progress_bar.update_processed_size_signal.emit(x)
            
            try:
                self.web.set_file_info(self.filenames, processed_size_callback=_set_processed_size)
                self.app.cleanup_filenames.append(self.web.zip_filename)

                # Only continue if the server hasn't been canceled
                if self.server_status.status != self.server_status.STATUS_STOPPED:
                    self.starting_server_step3.emit()
                    self.start_server_finished.emit()
            except OSError as e:
                self.starting_server_error.emit(e.strerror)
                return

        t = threading.Thread(target=finish_starting_server, kwargs={'self': self})
        t.daemon = True
        t.start()
    
    def start_server_step3_custom(self):
        """
        Step 3 in starting the server. Remove zip progess bar, and display large filesize
        warning, if applicable.
        """
        # Remove zip progress bar
        if self._zip_progress_bar is not None:
            self.status_bar.removeWidget(self._zip_progress_bar)
            self._zip_progress_bar = None

        # Warn about sending large files over Tor
        if self.web.zip_filesize >= 157286400:  # 150mb
            self.filesize_warning.setText(strings._("large_filesize", True))
            self.filesize_warning.show()
    
    def start_server_error_custom(self):
        """
        Start server error.
        """
        if self._zip_progress_bar is not None:
            self.status_bar.removeWidget(self._zip_progress_bar)
            self._zip_progress_bar = None
    
    def stop_server_custom(self):
        """
        Stop server.
        """
        # Remove the progress bar
        if self._zip_progress_bar is not None:
            self.status_bar.removeWidget(self._zip_progress_bar)
            self._zip_progress_bar = None

        self.filesize_warning.hide()
        self.downloads_in_progress = 0
        self.downloads_completed = 0
        self.update_downloads_in_progress(0)
        self.file_selection.file_list.adjustSize()

    def handle_tor_broke_custom(self):
        """
        Connection to Tor broke.
        """
        self.primary_action.hide()
        self.info_widget.hide()

    def handle_request_load(self, event):
        """
        Handle REQUEST_LOAD event.
        """
        self.system_tray.showMessage(strings._('systray_page_loaded_title', True), strings._('systray_download_page_loaded_message', True))

    def handle_request_download(self, event):
        """
        Handle REQUEST_DOWNLOAD event.
        """
        self.downloads.no_downloads_label.hide()
        self.downloads.add_download(event["data"]["id"], self.web.zip_filesize)
        self.new_download = True
        self.downloads_in_progress += 1
        self.update_downloads_in_progress(self.downloads_in_progress)

        self.system_tray.showMessage(strings._('systray_download_started_title', True), strings._('systray_download_started_message', True))

    def handle_request_progress(self, event):
        """
        Handle REQUEST_PROGRESS event.
        """
        self.downloads.update_download(event["data"]["id"], event["data"]["bytes"])

        # Is the download complete?
        if event["data"]["bytes"] == self.web.zip_filesize:
            self.system_tray.showMessage(strings._('systray_download_completed_title', True), strings._('systray_download_completed_message', True))

            # Update the total 'completed downloads' info
            self.downloads_completed += 1
            self.update_downloads_completed(self.downloads_completed)
            # Update the 'in progress downloads' info
            self.downloads_in_progress -= 1
            self.update_downloads_in_progress(self.downloads_in_progress)

            # close on finish?
            if not self.web.stay_open:
                self.server_status.stop_server()
                self.status_bar.clearMessage()
                self.server_status_label.setText(strings._('closing_automatically', True))
        else:
            if self.server_status.status == self.server_status.STATUS_STOPPED:
                self.downloads.cancel_download(event["data"]["id"])
                self.downloads_in_progress = 0
                self.update_downloads_in_progress(self.downloads_in_progress)

    def handle_request_canceled(self, event):
        """
        Handle REQUEST_CANCELED event.
        """
        self.downloads.cancel_download(event["data"]["id"])

        # Update the 'in progress downloads' info
        self.downloads_in_progress -= 1
        self.update_downloads_in_progress(self.downloads_in_progress)
        self.system_tray.showMessage(strings._('systray_download_canceled_title', True), strings._('systray_download_canceled_message', True))

    def on_reload_settings(self):
        """
        If there were some files listed for sharing, we should be ok to re-enable
        the 'Start Sharing' button now.
        """
        if self.server_status.file_selection.get_num_files() > 0:
            self.primary_action.show()
            self.info_widget.show()

    def update_primary_action(self):
        # Show or hide primary action layout
        file_count = self.file_selection.file_list.count()
        if file_count > 0:
            self.primary_action.show()
            self.info_widget.show()

            # Update the file count in the info label
            total_size_bytes = 0
            for index in range(self.file_selection.file_list.count()):
                item = self.file_selection.file_list.item(index)
                total_size_bytes += item.size_bytes
            total_size_readable = self.common.human_readable_filesize(total_size_bytes)

            if file_count > 1:
                self.info_label.setText(strings._('gui_file_info', True).format(file_count, total_size_readable))
            else:
                self.info_label.setText(strings._('gui_file_info_single', True).format(file_count, total_size_readable))

        else:
            self.primary_action.hide()
            self.info_widget.hide()

        # Resize window
        self.adjustSize()

    def downloads_toggled(self, checked):
        """
        When the 'Show/hide downloads' button is toggled, show or hide the downloads window.
        """
        self.common.log('ShareMode', 'toggle_downloads')
        if checked:
            self.downloads.downloads_container.show()
        else:
            self.downloads.downloads_container.hide()

    def reset_info_counters(self):
        """
        Set the info counters back to zero.
        """
        self.update_downloads_completed(0)
        self.update_downloads_in_progress(0)
        self.info_show_downloads.setIcon(QtGui.QIcon(self.common.get_resource_path('images/download_window_gray.png')))
        self.downloads.no_downloads_label.show()
        self.downloads.downloads_container.resize(self.downloads.downloads_container.sizeHint())

    def update_downloads_completed(self, count):
        """
        Update the 'Downloads completed' info widget.
        """
        if count == 0:
            self.info_completed_downloads_image = self.common.get_resource_path('images/download_completed_none.png')
        else:
            self.info_completed_downloads_image = self.common.get_resource_path('images/download_completed.png')
        self.info_completed_downloads_count.setText('<img src="{0:s}" /> {1:d}'.format(self.info_completed_downloads_image, count))
        self.info_completed_downloads_count.setToolTip(strings._('info_completed_downloads_tooltip', True).format(count))

    def update_downloads_in_progress(self, count):
        """
        Update the 'Downloads in progress' info widget.
        """
        if count == 0:
            self.info_in_progress_downloads_image = self.common.get_resource_path('images/download_in_progress_none.png')
        else:
            self.info_in_progress_downloads_image = self.common.get_resource_path('images/download_in_progress.png')
            self.info_show_downloads.setIcon(QtGui.QIcon(self.common.get_resource_path('images/download_window_green.png')))
        self.info_in_progress_downloads_count.setText('<img src="{0:s}" /> {1:d}'.format(self.info_in_progress_downloads_image, count))
        self.info_in_progress_downloads_count.setToolTip(strings._('info_in_progress_downloads_tooltip', True).format(count))
    
    @staticmethod
    def _compute_total_size(filenames):
        total_size = 0
        for filename in filenames:
            if os.path.isfile(filename):
                total_size += os.path.getsize(filename)
            if os.path.isdir(filename):
                total_size += Common.dir_size(filename)
        return total_size


class ZipProgressBar(QtWidgets.QProgressBar):
    update_processed_size_signal = QtCore.pyqtSignal(int)

    def __init__(self, total_files_size):
        super(ZipProgressBar, self).__init__()
        self.setMaximumHeight(20)
        self.setMinimumWidth(200)
        self.setValue(0)
        self.setFormat(strings._('zip_progress_bar_format'))
        cssStyleData ="""
        QProgressBar {
            border: 1px solid #4e064f;
            background-color: #ffffff !important;
            text-align: center;
            color: #9b9b9b;
        }

        QProgressBar::chunk {
            border: 0px;
            background-color: #4e064f;
            width: 10px;
        }"""
        self.setStyleSheet(cssStyleData)

        self._total_files_size = total_files_size
        self._processed_size = 0

        self.update_processed_size_signal.connect(self.update_processed_size)

    @property
    def total_files_size(self):
        return self._total_files_size

    @total_files_size.setter
    def total_files_size(self, val):
        self._total_files_size = val

    @property
    def processed_size(self):
        return self._processed_size

    @processed_size.setter
    def processed_size(self, val):
        self.update_processed_size(val)

    def update_processed_size(self, val):
        self._processed_size = val
        if self.processed_size < self.total_files_size:
            self.setValue(int((self.processed_size * 100) / self.total_files_size))
        elif self.total_files_size != 0:
            self.setValue(100)
        else:
            self.setValue(0)