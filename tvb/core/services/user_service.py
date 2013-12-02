# -*- coding: utf-8 -*-
#
#
# TheVirtualBrain-Framework Package. This package holds all Data Management, and 
# Web-UI helpful to run brain-simulations. To use it, you also need do download
# TheVirtualBrain-Scientific Package (for simulators). See content of the
# documentation-folder for more details. See also http://www.thevirtualbrain.org
#
# (c) 2012-2013, Baycrest Centre for Geriatric Care ("Baycrest")
#
# This program is free software; you can redistribute it and/or modify it under 
# the terms of the GNU General Public License version 2 as published by the Free
# Software Foundation. This program is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
# License for more details. You should have received a copy of the GNU General 
# Public License along with this program; if not, you can download it here
# http://www.gnu.org/licenses/old-licenses/gpl-2.0
#
#
#   CITATION:
# When using The Virtual Brain for scientific publications, please cite it as follows:
#
#   Paula Sanz Leon, Stuart A. Knock, M. Marmaduke Woodman, Lia Domide,
#   Jochen Mersmann, Anthony R. McIntosh, Viktor Jirsa (2013)
#       The Virtual Brain: a simulator of primate brain network dynamics.
#   Frontiers in Neuroinformatics (7:10. doi: 10.3389/fninf.2013.00010)
#
#

"""
Service layer for USER entities. 
   
.. moduleauthor:: Lia Domide <lia.domide@codemart.ro>
"""
import threading
from random import randint
from hashlib import md5
from inspect import stack
from tvb.basic.config.settings import TVBSettings as cfg
from tvb.basic.logger.builder import get_logger
from tvb.core.decorators import synchronized
from tvb.core.entities import model
from tvb.core.entities.storage import dao
from tvb.core.entities.file.files_update_manager import FilesUpdateManager
from tvb.core.services import email_sender
from tvb.core.services.exceptions import UsernameException
from tvb.core.services.settings_service import SettingsService
from tvb.core.services.event_handlers import handle_event


FROM_ADDRESS = 'donotreply@thevirtualbrain.org'
SUBJECT_REGISTER = '[TVB] Registration Confirmation'
SUBJECT_VALIDATE = '[TVB] Account validated'
SUBJECT_RECOVERY = '[TVB] Recover password'
TEXT_RECOVERY = 'A new password was generated for you. Please login with \
the below password and change it to one you can easily remember as soon as \
possible.\n Thank you.\n\n Password: %s'
TEXT_DISPLAY = "Thank you! Please check your email for further details!"
TEXT_CREATE = (',\n\nYour registration has been notified to the administrators '
               + 'of The Virtual Brain Project; you will receive an mail as '
               + 'soon as the administrator has validated your registration.'
               + ' \n\nThank you for registering!\nTVB Team')
TEXT_CREATE_TO_ADMIN = 'New member requires validation. Go to this url to validate '
TEXT_VALIDATED = ',\n\nYour registration has been validated by TVB Administrator, Please proceed with the login at '
KEY_USERNAME = "username"
KEY_PASSWORD = "password"
KEY_EMAIL = "email"
KEY_ROLE = "role"
KEY_COMMENT = "comment"
DEFAULT_PASS_LENGTH = 10
USERS_PAGE_SIZE = 7
FILE_UPGRADE_LOCK = threading.Lock()



class UserService:
    """
    CRUD methods for USER entities are here.
    """
    USER_ROLES = model.USER_ROLES


    def __init__(self):
        self.logger = get_logger(self.__class__.__module__)


    def create_user(self, username=None, password=None, password2=None,
                    role=None, email=None, comment=None, email_msg=None, validated=False):
        """
        Service Layer for creating a new user.
        """
        #Basic fields validation.
        if (username is None) or len(username) < 1:
            raise UsernameException("Empty UserName!")
        if (password is None) or len(password) < 1:
            raise UsernameException("Empty password!")
        if password2 is None:
            password2 = password
        if password != password2:
            raise UsernameException("Passwords do not match!")
        try:
            user_validated = (role == 'ADMINISTRATOR') or validated
            user = model.User(username, password, email, user_validated, role)
            if email_msg is None:
                email_msg = 'Hello ' + username + TEXT_CREATE
            admin_msg = (TEXT_CREATE_TO_ADMIN + username + ' :\n ' + cfg.BASE_URL +
                         'user/validate/' + username + '\n\n"' + str(comment) + '"')
            self.logger.info("Registering user " + username + " !")
            if role != 'ADMINISTRATOR' and email is not None:
                admins = UserService.get_administrators()
                admin = admins[randint(0, len(admins) - 1)]
                if admin.email is not None and (admin.email != cfg.DEFAULT_ADMIN_EMAIL or
                                                cfg.SERVER_IP != cfg.LOCALHOST):
                    # Do not send validation email in case default admin email
                    # remained unchanged but TVB in locally deployed....
                    email_sender.send(FROM_ADDRESS, admin.email, SUBJECT_REGISTER, admin_msg)
                    self.logger.debug("Email sent to:" + admin.email + " for validating user:" + username + " !")
                email_sender.send(FROM_ADDRESS, email, SUBJECT_REGISTER, email_msg)
                self.logger.debug("Email sent to:" + email + " for notifying new user:" + username + " !")
            user = dao.store_entity(user)
            if not SettingsService.is_first_run():
                handle_event(".".join([self.__class__.__name__, stack()[0][3]]), user)
            return TEXT_DISPLAY
        except Exception, excep:
            self.logger.error("Could not create user!")
            self.logger.exception(excep)
            raise UsernameException(excep.message)


    def reset_password(self, **data):
        """
        Service Layer for resetting a password.
        """
        if (KEY_USERNAME not in data) or len(data[KEY_USERNAME]) < 1:
            raise UsernameException("Empty UserName!")
        if (KEY_EMAIL not in data) or len(data[KEY_EMAIL]) < 1:
            raise UsernameException("Empty Email!")

        old_pass, user = None, None
        try:
            user_name = data[KEY_USERNAME]
            email = data[KEY_EMAIL]
            user = dao.get_user_by_name_email(user_name, email)
            if user is None:
                raise UsernameException("Given credentials don't match!")

            old_pass = user.password
            new_pass = ''.join(chr(randint(48, 122)) for _ in range(DEFAULT_PASS_LENGTH))
            user.password = md5(new_pass).hexdigest()
            self.edit_user(user, old_pass)
            self.logger.info("Setting new password for user " + user_name + " !")
            email_sender.send(FROM_ADDRESS, email, SUBJECT_RECOVERY, TEXT_RECOVERY % (new_pass,))
            return TEXT_DISPLAY
        except Exception, excep:
            if old_pass and len(old_pass) > 1 and user:
                user.password = old_pass
                dao.store_entity(user)
            self.logger.error("Could not change user password!")
            self.logger.exception(excep)
            raise UsernameException(excep.message)


    @staticmethod
    def is_username_valid(name):
        """
        Service layer for checking if a given UserName is unique or not.
        """
        users_no = dao.count_users_for_name(name)
        if users_no > 0:
            return False
        return True


    def validate_user(self, name='', user_id=None):
        """
        Service layer for editing a user and validating the account.
        """
        try:
            if user_id:
                user = dao.get_user_by_id(user_id)
            else:
                user = dao.get_user_by_name(name)
            if user is None or user.validated:
                self.logger.warning("UserName not found or already validated:" + name)
                return False
            user.validated = True
            user = dao.store_entity(user)
            self.logger.debug("Sending validation email for userName=" + name + " to address=" + user.email)
            email_sender.send(FROM_ADDRESS, user.email, SUBJECT_VALIDATE,
                              "Hello " + name + TEXT_VALIDATED + cfg.BASE_URL + "user/")
            self.logger.info("User:" + name + " was validated successfully" + " and notification email sent!")
            return True
        except Exception, excep:
            self.logger.warning('Could not validate user:')
            self.logger.warning('WARNING : ' + str(excep))
            return False


    @staticmethod
    def check_login(username, password):
        """
        Service layer to check if given UserName and Password are according to DB.
        """
        user = dao.get_user_by_name(username)
        if user is not None and user.password == md5(password).hexdigest() and user.validated:
            return user
        else:
            return None


    def get_users_for_project(self, user_name, project_id, page=1):
        """
        Return tuple: (All Users except the project administrator, Project Members).
        Parameter "user_name" is the current user. 
        Parameter "user_name" is used for new projects (project_id is None). 
        When "project_id" not None, parameter "user_name" is ignored.       
        """
        try:
            admin_name = user_name
            if project_id is not None:
                project = dao.get_project_by_id(project_id)
                if project is not None:
                    admin_name = project.administrator.username
            all_users, total_pages = self.retrieve_all_users(admin_name, page)
            members = dao.get_members_of_project(project_id)
            return all_users, members, total_pages
        except Exception, excep:
            self.logger.error("Invalid userName or project identifier")
            self.logger.exception(excep)
            raise UsernameException(excep.message)


    @staticmethod
    def retrieve_all_users(username, current_page=1):
        """
        Return all users from the database except the given user
        """
        start_idx = USERS_PAGE_SIZE * (current_page - 1)
        total = dao.get_all_users(username, is_count=True)
        end_idx = (USERS_PAGE_SIZE if total >= start_idx + USERS_PAGE_SIZE else total - start_idx)
        user_list = dao.get_all_users(username, start_idx, end_idx)
        pages_no = total // USERS_PAGE_SIZE + (1 if total % USERS_PAGE_SIZE else 0)
        return user_list, pages_no


    def edit_user(self, edited_user, old_password=None):
        """
        Retrieve a user by and id, then modify it's role and validate status.
        """
        if edited_user.validated:
            self.validate_user(user_id=edited_user.id)
        user = dao.get_user_by_id(edited_user.id)
        user.role = edited_user.role
        user.validated = edited_user.validated
        if old_password is not None:
            if user.password == old_password:
                user.password = edited_user.password
            else:
                raise UsernameException("Invalid old password!")
        user.email = edited_user.email
        for key, value in edited_user.preferences.iteritems():
            user.preferences[key] = value
        dao.store_entity(user)
        if user.is_administrator():
            cfg.update_config_file({SettingsService.KEY_ADMIN_EMAIL: user.email,
                                    SettingsService.KEY_ADMIN_PWD: user.password})


    def delete_user(self, user_id):
        """ 
        Delete a user with a given ID. 
        Return True when successfully, or False."""
        try:
            dao.delete_user(user_id)
            return True
        except Exception, excep:
            self.logger.exception(excep)
            return False


    @staticmethod
    def get_administrators():
        """Retrieve system administrators.
        Will be used for sending emails, for example."""
        return dao.get_administrators()


    @staticmethod
    def save_project_to_user(user_id, project_id):
        """
        Mark for current user that the given project is the last one selected.
        """
        user = dao.get_user_by_id(user_id)
        user.selected_project = project_id
        dao.store_entity(user)


    @staticmethod
    def get_user_by_id(user_id):
        """
        Retrieves a user by its id.
        """
        return dao.get_user_by_id(user_id)


    @synchronized(FILE_UPGRADE_LOCK)
    def upgrade_file_storage(self):
        """
        For the given user upgrade all DataType files storage.
        
        :returns: a two entry tuple (status, message) where status is a boolean that is True in case the upgrade
             was successful for all DataTypes and False otherwise, and message is a status update message.
        """
        status = None
        message = ''
        if cfg.DATA_CHECKED_TO_VERSION < cfg.DATA_VERSION:
            self.logger.info("Starting to upgrade all DataType file storage.")
            status, message = FilesUpdateManager().upgrade_all_files_from_storage()
        return status, message
         
            