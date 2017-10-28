#!/usr/bin/python
#
# Raspberry Pi secury system with motion detection, camera & mail notification,
# Dropbox & IFTTT support.
#
# Copyright (C) 2015 volcain <work@volcain.io>
#
# Script sends an email as soon as the motion sensor is triggered.
# The camera is capturing continuously images for a period of 60 seconds with
# a delay of 10 seconds (this means 10 pictures in 60 seconds)

# import libs
import RPi.GPIO as GPIO
import time
import picamera
import smtplib
import os
import sys
import logging
import email.utils
import json
import requests

# import modules
from datetime import datetime
from smtplib import SMTPException
from email.mime.text import MIMEText
from logging import config
from simplejson.scanner import JSONDecodeError
from dropbox import client, rest, session
from dropbox.rest import ErrorResponse
from requests import RequestException

# declare global vars with default values (do not change)
LOGGER = None
SCRIPT_PATH = None
DROPBOX_CLIENT = None
LOG_CONF_FILENAME = 'logging.conf'
APP_CONF_FILENAME = 'call_home_conf.json'
IMG_DIR_NAME = 'images'
LOG_DIR_NAME = 'logs'

# CAUTION: following variables are declared in the file 'call_home_conf.json'
# this declartion is only used as default values
# (e.g. in case if the config file could not be loaded)
DEBUG_RUN_ONCE = 'false'
DEBUG_ENABLE_LOGGING = 'true'
CAMERA_ENABLE = 'true'
CAMERA_LED_ON = 'false'
CAMERA_REC_TIME_DELAY = 60
# set default resolution: 480
CAMERA_RESOLUTION_HEIGHT = 800
# set default resolution: 720
CAMERA_RESOLUTION_WIDTH = 1200
CAMERA_WARMUP_TIME = 2
DROPBOX_ENABLE = 'true'
# optional directory, where you want to store your uploaded files
DROPBOX_DIR_NAME = 'motion_cam_mail'
GPIO_CHANNEL = 18
IFTTT_ENABLE = 'false'
# set your event name (how-to: https://ifttt.com/maker)
IFTTT_EVENT_NAME = ''
# set your channel key (how-to: https://ifttt.com/maker)
IFTTT_CHANNEL_KEY = ''
# how many images?
IMAGE_COUNT = 10
IMAGE_FILETYPE = '.jpg'
IMAGE_NAME_PREFIX = 'motion_detected_at_'
MAIL_ENABLE = 'true'
MAIL_ENCRYPT = 'true'
MAIL_NAME_FROM = 'SB Tank Erlangen'
MAIL_NAME_TO = 'volcain.io'
MAIL_SMTP_SERVER = 'w010191c.kasserver.com'
MAIL_SMTP_PORT = 587
MAIL_SMTP_USERNAME = 'info@sbtank-erlangen.de'
MAIL_SMTP_PASSWORD = 'VUq37VVsoZ3vphrd'
MAIL_RECIPIENT_EMAIL = 'raspi@volcain.org'
MAIL_SUBJECT = 'ALERT: motion detected @'
MAIL_TEXT = 'Go check your Dropbox folder'


# this function is the main entry point
# reading configuration files & setting variables & starting the program
# @profile # uncomment this line for performance testing with 'line_profiler'
def init():
    # set script path
    setScriptPath()

    # check if log configuration exists
    if not os.path.isfile(getLoggingConfFile()):
        error_msg = 'logger config file is missing: %s' % getLoggingConfFile()
        raise IOError(error_msg)
    else:
        setLogger()

    # check if configuration file exists & get configuration
    if os.path.isfile(getAppConfFile()):
        global DEBUG_RUN_ONCE, DEBUG_ENABLE_LOGGING
        global CAMERA_ENABLE, CAMERA_LED_ON, CAMERA_REC_TIME_DELAY
        global CAMERA_RESOLUTION_HEIGHT, CAMERA_RESOLUTION_WIDTH
        global CAMERA_WARM_UP_TIME
        global GPIO_CHANNEL
        global DROPBOX_ENABLE, DROPBOX_DIR_NAME
        global IFTTT_ENABLE, IFTTT_EVENT_NAME, IFTTT_CHANNEL_KEY
        global IMAGE_COUNT, IMAGE_FILETYPE, IMAGE_NAME_PREFIX
        global MAIL_ENABLE, MAIL_ENCRYPT, MAIL_NAME_FROM, MAIL_NAME_TO
        global MAIL_SMTP_SERVER, MAIL_SMTP_PORT, MAIL_SMTP_USERNAME
        global MAIL_SMTP_PASSWORD, MAIL_RECIPIENT_EMAIL, MAIL_SUBJECT
        global MAIL_TEXT

        try:
            # read configuration
            CONF = json.load(open(getAppConfFile()))

            # set configuration
            DEBUG_RUN_ONCE = CONF['debug']['run_once']
            DEBUG_ENABLE_LOGGING = CONF['debug']['enable_logging']
            CAMERA_ENABLE = CONF['camera']['enable']
            CAMERA_LED_ON = CONF['camera']['led_on']
            CAMERA_REC_TIME_DELAY = CONF['camera']['recording_time_delay']
            CAMERA_RESOLUTION_HEIGHT = CONF['camera']['resolution_height']
            CAMERA_RESOLUTION_WIDTH = CONF['camera']['resolution_width']
            CAMERA_WARM_UP_TIME = CONF['camera']['warm_up_time']
            DROPBOX_ENABLE = CONF['dropbox']['enable']
            DROPBOX_DIR_NAME = CONF['dropbox']['dir_name']
            GPIO_CHANNEL = CONF['gpio']['channel']
            IFTTT_ENABLE = CONF['ifttt']['enable']
            IFTTT_EVENT_NAME = CONF['ifttt']['event_name']
            IFTTT_CHANNEL_KEY = CONF['ifttt']['channel_key']
            IMAGE_COUNT = CONF['image']['count']
            IMAGE_FILETYPE = CONF['image']['filetype']
            IMAGE_NAME_PREFIX = CONF['image']['name_prefix']
            MAIL_ENABLE = CONF['mail']['enable']
            MAIL_ENCRYPT = CONF['mail']['encrypt']
            MAIL_NAME_FROM = CONF['mail']['name_from']
            MAIL_NAME_TO = CONF['mail']['name_to']
            MAIL_RECIPIENT_EMAIL = CONF['mail']['recipient_email']
            MAIL_SMTP_SERVER = CONF['mail']['smtp_server']
            MAIL_SMTP_PORT = CONF['mail']['smtp_port']
            MAIL_SMTP_USERNAME = CONF['mail']['smtp_username']
            MAIL_SMTP_PASSWORD = CONF['mail']['smtp_password']
            MAIL_SUBJECT = CONF['mail']['subject']
            MAIL_TEXT = CONF['mail']['text']
        except JSONDecodeError:
            warn_msg = 'using default values. %s is not a valid JSON document.' % getAppConfFile()
            log('warn', warn_msg)

    # check if image directory exists & create it if necessary
    if not os.path.exists(getImgDirName()):
        os.makedirs(getImgDirName())

    # check if log directory exists & create it if necessary
    if not os.path.exists(getLogDirName()):
        os.makedirs(getLogDirName())

    # check, if user is root & exit program otherwise start the magic
    if not os.getuid() == 0:
        log('error', 'user must be root in order to execute this script')
    else:
        main()


# upload images to dropbox via python
# @profile # uncomment this line for performance testing with 'line_profiler'
def setDropboxClient():
    global DROPBOX_CLIENT

    if (DROPBOX_CLIENT is None):
        # Get your app key and secret from the Dropbox developer website
        try:
            sess = session.DropboxSession('e2jvd445bhji9as', 'pscaalzdcidsgem', 'app_folder')
            sess.set_token('owlv0c0mkh1xirc2', 'hz134h95idlsbaf')
            # get instance of dropbox client
            DROPBOX_CLIENT = client.DropboxClient(sess)
        except ErrorResponse as err:
            log('error', err.user_error_msg)

    return DROPBOX_CLIENT


# read configuration file & create logger
# @profile # uncomment this line for performance testing with 'line_profiler'
def setLogger():
        global LOGGER

        if (LOGGER is None):
            logging.config.fileConfig(getLoggingConfFile())
            logging.captureWarnings(True)
            LOGGER = logging.getLogger('motion-cam-mail')


# @profile # uncomment this line for performance testing with 'line_profiler'
def setScriptPath():
    global SCRIPT_PATH
    SCRIPT_PATH = os.path.abspath(os.path.dirname(sys.argv[0])) + os.path.sep
    return SCRIPT_PATH


# log messages whereas 'debug' is the default log level
# logLevel: 'debug', 'info', 'warn', 'error', 'critical'
# logMessage: message to log
# @profile # uncomment this line for performance testing with 'line_profiler'
def log(logLevel, logMessage):
    if isLogging():
        if isinstance(logLevel, str):
            if ('debug' == logLevel.lower()):
                LOGGER.debug(logMessage)
            elif ('info' == logLevel.lower()):
                LOGGER.info(logMessage)
            elif ('warn' == logLevel.lower()):
                LOGGER.warn(logMessage)
            elif ('error' == logLevel.lower()):
                LOGGER.error(logMessage)
            elif ('critical' == logLevel.lower()):
                LOGGER.critical(logMessage)
            else:
                LOGGER.debug(logMessage)
        else:
            LOGGER.debug(logMessage)


# @profile # uncomment this line for performance testing with 'line_profiler'
def run_once():
    return bool('true' == DEBUG_RUN_ONCE)


# @profile # uncomment this line for performance testing with 'line_profiler'
def isLogging():
    return bool('true' == DEBUG_ENABLE_LOGGING)


# @profile # uncomment this line for performance testing with 'line_profiler'
def isCamera():
    return bool('true' == CAMERA_ENABLE)


# @profile # uncomment this line for performance testing with 'line_profiler'
def isDropbox():
    return bool('true' == DROPBOX_ENABLE)


# @profile # uncomment this line for performance testing with 'line_profiler'
def isIFTTT():
    return bool('true' == IFTTT_ENABLE)


# @profile # uncomment this line for performance testing with 'line_profiler'
def isMail():
    return bool('true' == MAIL_ENABLE)


# @profile # uncomment this line for performance testing with 'line_profiler'
def getLoggingConfFile():
    return SCRIPT_PATH + LOG_CONF_FILENAME


# @profile # uncomment this line for performance testing with 'line_profiler'
def getAppConfFile():
    return SCRIPT_PATH + APP_CONF_FILENAME


# @profile # uncomment this line for performance testing with 'line_profiler'
def getImgDirName():
    return SCRIPT_PATH + IMG_DIR_NAME


# @profile # uncomment this line for performance testing with 'line_profiler'
def getLogDirName():
    return SCRIPT_PATH + LOG_DIR_NAME


# take up to 10 pictures with a 1 minute delay
# @profile # uncomment this line for performance testing with 'line_profiler'
def takePictures():
    if isCamera():
        with picamera.PiCamera() as camera:
            log('info', 'initializing camera...')
            if (CAMERA_RESOLUTION_WIDTH > 0 and CAMERA_RESOLUTION_HEIGHT > 0):
                camera.resolution = (CAMERA_RESOLUTION_WIDTH, CAMERA_RESOLUTION_HEIGHT)
            camera.led = not bool('false' == CAMERA_LED_ON)
            camera.start_preview()

            log('info', 'taking pictures...')
            try:
                picture_count = 0
                while (IMAGE_COUNT > picture_count):
                    filename = IMAGE_NAME_PREFIX + datetime.now().strftime("%Y%m%d_%H%M%S") + IMAGE_FILETYPE
                    fileToUpload = getImgDirName() + os.path.sep + filename
                    camera.capture(fileToUpload)
                    log('info', 'image captured: %s' % filename)
                    uploadToDropbox(fileToUpload)
                    picture_count += 1
                    if not isDropbox():
                        time.sleep(CAMERA_REC_TIME_DELAY)
            finally:
                log('info', 'stopping camera...')
                camera.stop_preview()
    else:
        log('warn', 'camera is disabled...')


# upload images to dropbox. Uploaded files will be stored in the specified
# folder name (DROPBOX_DIR_NAME)
# @profile # uncomment this line for performance testing with 'line_profiler'
def uploadToDropbox(fileToUpload):
    if isDropbox():
        try:
            setDropboxClient()
            # create dropbox client, if necessary
            fileObj = open(fileToUpload, 'rb')
            fullPath = os.path.sep + DROPBOX_DIR_NAME + os.path.sep + os.path.basename(fileToUpload)
            response = DROPBOX_CLIENT.put_file(fullPath, fileObj)
        except IOError as ioError:
            log('error', 'I/O error ({0}): {1}'.format(ioError.errno, ioError.strerror))
        except ErrorResponse as err:
            log('error', err.error_msg)
        else:
            log('info', 'response: %s' % response)
            log('info', 'image uploaded: %s' % os.path.basename(fileToUpload))
    else:
        log('warn', 'dropbox is disabled...')


# send an email with alert notification in plain text
# @profile # uncomment this line for performance testing with 'line_profiler'
def sendEmail():
    if isMail():
        MESSAGE = MIMEText(MAIL_TEXT)
        MESSAGE['From'] = email.utils.formataddr((MAIL_NAME_FROM, MAIL_SMTP_USERNAME))
        MESSAGE['To'] = email.utils.formataddr((MAIL_NAME_TO, MAIL_RECIPIENT_EMAIL))
        MESSAGE['Subject'] = MAIL_SUBJECT + datetime.now().strftime('%d.%m.%Y - %H:%M')

        log('info', 'opening mail connection to send mail')
        server = smtplib.SMTP(MAIL_SMTP_SERVER, MAIL_SMTP_PORT)
        try:
            server.ehlo()
            # if config value set, try to encrypt session
            if bool('true' == MAIL_ENCRYPT) and server.has_extn('STARTTLS'):
                server.starttls()
                server.ehlo()

            server.login(MAIL_SMTP_USERNAME, MAIL_SMTP_PASSWORD)
            server.sendmail(MAIL_SMTP_USERNAME, MAIL_RECIPIENT_EMAIL, MESSAGE.as_string())
            log('info', 'mail is sent successfully')
        except SMTPException as smtpException:
            log('error', 'SMTP error ({0}): {1}'.format(smtpException.errno, smtpException.strerror))
        finally:
            log('info', 'closing mail connection')
            server.quit()
    else:
        log('warn', 'mail is disabled...')


# fire a post request to the ifttt maker channel to trigger an action e.g.
# mail notification, push notification or sms
# @profile # uncomment this line for performance testing with 'line_profiler'
def notifyIFTTT():
    if isIFTTT():
        try:
            requests.post('https://maker.ifttt.com/trigger/' + IFTTT_EVENT_NAME + '/with/key/' + IFTTT_CHANNEL_KEY)
            log('info', 'IFTTT notification send successfully')
        except RequestException as requestEx:
            log('error', 'Request Error ({0}): {1}'.format(requestEx.errno, requestEx.strerror))
    else:
        log('warn', 'IFTTT is disabled...')


# @profile # uncomment this line for performance testing with 'line_profiler'
def main():
    # set up pins & pir state
    log('info', 'setting up GPIO...')
    GPIO_PIN_VALUE = 0
    GPIO_PIN_VALUE_OLD = 0
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(GPIO_CHANNEL, GPIO.IN)

    try:
        log('info', 'waiting for PIR sensor to settle...')
        while GPIO.input(GPIO_CHANNEL) == 1:
            GPIO_PIN_VALUE = 0

        log('info', 'PIR sensor is ready...')

        while True:
            GPIO_PIN_VALUE = GPIO.input(GPIO_CHANNEL)

            if GPIO_PIN_VALUE == 1 and GPIO_PIN_VALUE_OLD == 0:
                log('info', 'PIR sensor has detected a motion')
                sendEmail()
                notifyIFTTT()
                takePictures()
                GPIO_PIN_VALUE_OLD = 1
                time.sleep(0.1)
                if run_once():
                    break
            elif GPIO_PIN_VALUE == 0 and GPIO_PIN_VALUE_OLD == 1:
                log('info', 'reseting PIR sensor')
                GPIO_PIN_VALUE_OLD = 0
                time.sleep(0.01)

    except KeyboardInterrupt:
        log('warn', 'program interrupted by user')
        GPIO.cleanup()


if __name__ == '__main__':
    init()
