"""
.. module:: Katna.video
    :platform: OS X
    :synopsis: This module has functions related to key frame extraction 
"""
import os.path
import os
import sys
import numpy as np
import cv2
import errno
from Katna.decorators import VideoDecorators
from Katna.decorators import FileDecorators

from Katna.frame_extractor import FrameExtractor
from Katna.image_selector import ImageSelector
from Katna.video_compressor import VideoCompressor
import Katna.helper_functions as helper

import Katna.config as config
import subprocess
import re
import ffmpy
from imageio_ffmpeg import get_ffmpeg_exe
from multiprocessing import Pool, Process, cpu_count

class Video(object):
    """Class for all video frames operations

    :param object: base class inheritance
    :type object: class:`Object`
    """

    def __init__(self):
        # Find out location of ffmpeg binary on system
        helper._set_ffmpeg_binary_path()
        # If the duration of the clipped video is less than **min_video_duration**
        # then, the clip will be added with the previous clipped
        self.min_video_duration = config.Video.min_video_duration
        # Calculating optimum number of processes for multiprocessing
        self.n_processes = cpu_count() // 2 - 1
        if self.n_processes < 1:
            self.n_processes = None

        # Folder to save the videos after clipping
        self.temp_folder = os.path.abspath(os.path.join("clipped"))
        if not os.path.isdir(self.temp_folder):
            os.mkdir(self.temp_folder)

    def _remove_clips(self, video_clips):
        """Remove video clips from the temp directory given list of video clips

        :param video_clips: [description]
        :type video_clips: [type]
        """
        for clip in video_clips:
            try:
                os.remove(clip)
            except OSError:
                print("Error in removing clip: " + clip)
            # print(clip, " removed!")

    @FileDecorators.validate_dir_path
    def extract_keyframes_from_videos_dir(self, no_of_frames, dir_path):
        """Returns best key images/frames from the videos in the given directory.
        you need to mention number of keyframes as well as directory path
        containing videos. Function returns python dictionary with key as filepath
        each dictionary element contains list of python numpy image objects as
        keyframes.

        :param no_of_frames: Number of key frames to be extracted
        :type no_of_frames: int, required
        :param dir_path: Directory location with videos
        :type dir_path: str, required
        :return: Dictionary with key as filepath and numpy.2darray Image objects
        :rtype: dict
        """

        all_videos_top_frames = {}

        for path, subdirs, files in os.walk(dir_path):
            for filename in files:
                filepath = os.path.join(path, filename)

                if helper._check_if_valid_video(filename):
                    video_file_path = os.path.join(path, filename)
                    video_top_frames = self.extract_video_keyframes(
                        no_of_frames, video_file_path
                    )
                    all_videos_top_frames[filepath] = video_top_frames

        return all_videos_top_frames

    @FileDecorators.validate_file_path
    def extract_video_keyframes(self, no_of_frames, file_path):
        """Returns a list of best key images/frames from a single video.

        :param no_of_frames: Number of key frames to be extracted
        :type no_of_frames: int, required
        :param file_path: video file location
        :type file_path: str, required
        :return: List of numpy.2darray Image objects
        :rtype: list
        """
        # Creating the multiprocessing pool
        self.pool_extractor = Pool(processes=self.n_processes)
        self.pool_selector = Pool(processes=self.n_processes)
        # Split the input video into chunks. Each split(video) will be stored
        # in a temp
        if not helper._check_if_valid_video(file_path):
            raise Exception("Invalid or corrupted video: " + file_path)

        chunked_videos = self._split(file_path)

        frame_extractor = FrameExtractor()

        # Passing all the clipped videos for  the frame extraction using map function of the
        # multiprocessing pool
        with self.pool_extractor:
            extracted_candidate_frames = self.pool_extractor.map(
                frame_extractor.extract_candidate_frames, chunked_videos
            )
            # Converting the nested list of extracted frames into 1D list
            extracted_candidate_frames = [
                frame for frames in extracted_candidate_frames for frame in frames
            ]

        self._remove_clips(chunked_videos)
        image_selector = ImageSelector(self.pool_selector)
        top_frames = image_selector.select_best_frames(
            extracted_candidate_frames, no_of_frames
        )

        return top_frames

    @FileDecorators.validate_file_path
    def compress_video(
        self,
        file_path,
        force_overwrite=False,
        crf_parameter=config.Video.video_compression_crf_parameter,
        output_video_codec=config.Video.video_compression_codec,
        out_dir_path="",
        out_file_name="",
    ):
        """Function to compress given input file

        :param file_path: Input file path
        :type file_path: str        
        :param force_overwrite: optional parameter if True then if there is \
        already a file in output file location function will overwrite it, defaults to False
        :type force_overwrite: bool, optional
        :param crf_parameter: Constant Rate Factor Parameter for controlling \
        amount of video compression to be applied, The range of the quantizer scale is 0-51:\
        where 0 is lossless, 23 is default, and 51 is worst possible.\
        It is recommend to keep this value between 20 to 30 \
        A lower value is a higher quality, you can change default value by changing \
        config.Video.video_compression_crf_parameter
        :type crf_parameter: int, optional
        :param output_video_codec: Type of video codec to choose, \
        Currently supported options are libx264 and libx265, libx264 is default option.\
        libx264 is more widely supported on different operating systems and platforms, \
        libx265 uses more advanced x265 codec and results in better compression and even less \
        output video sizes with same or better quality. Right now libx265 is not as widely compatible \
        on older versions of MacOS and Widows by default. If wider video compatibility is your goal \
        you should use libx264., you can change default value by changing \
        Katna.config.Video.video_compression_codec
        :type output_video_codec: str, optional
        :param out_dir_path: output folder path where you want output video to be saved, defaults to ""
        :type out_dir_path: str, optional
        :param out_file_name: output filename, if not mentioned it will be same as input filename, defaults to ""
        :type out_file_name: str, optional
        :raises Exception: raises FileNotFoundError Exception if input video file not found, also exception is raised in case output video file path already exist and force_overwrite is not set to True.
        :return: Status code Returns True if video compression was successfull else False
        :rtype: bool
        """
        # TODO add docstring for exeception 
        # Add details where libx265 will make sense
        
        if not helper._check_if_valid_video(file_path):
            raise Exception("Invalid or corrupted video: " + file_path)
        # Intialize video compression class
        video_compressor = VideoCompressor()
        # Run video compression
        status = video_compressor.compress_video(
            file_path,
            force_overwrite,
            crf_parameter,
            output_video_codec,
            out_dir_path,
            out_file_name,
        )
        return status

    @FileDecorators.validate_dir_path
    def compress_videos_from_dir(
        self,
        dir_path,
        force_overwrite=False,
        crf_parameter=config.Video.video_compression_crf_parameter,
        output_video_codec=config.Video.video_compression_codec,
        out_dir_path="",
        out_file_name="",
    ):
        """Function to compress input video files in a folder

        :param dir_path: Input folder path
        :type dir_path: str
        :param force_overwrite: optional parameter if True then if there is \
        already a file in output file location function will overwrite it, defaults to False
        :type force_overwrite: bool, optional
        :param crf_parameter: Constant Rate Factor Parameter for controlling \
        amount of video compression to be applied, The range of the quantizer scale is 0-51:\
        where 0 is lossless, 23 is default, and 51 is worst possible.\
        It is recommend to keep this value between 20 to 30 \
        A lower value is a higher quality, you can change default value by changing \
        config.Video.video_compression_crf_parameter
        :type crf_parameter: int, optional
        :param output_video_codec: Type of video codec to choose, \
        Currently supported options are libx264 and libx265, libx264 is default option.\
        libx264 is more widely supported on different operating systems and platforms, \
        libx265 uses more advanced x265 codec and results in better compression and even less \
        output video sizes with same or better quality. Right now libx265 is not as widely compatible \
        on older versions of MacOS and Widows by default. If wider video compatibility is your goal \
        you should use libx264., you can change default value by changing Katna.config.Video.video_compression_codec
        :type output_video_codec: str, optional
        :param out_dir_path: output folder path where you want output video to be saved, defaults to ""
        :type out_dir_path: str, optional
        :raises Exception: raises FileNotFoundError Exception if input video file not found, also exception is raised in case output video file path already exist and force_overwrite is not set to True.
        :return: Status code Returns True if video compression was successfull else False
        :rtype: bool
        """
        status = True
        list_of_videos_to_process = []
        # Collect all the valid video files inside folder
        for path, _, files in os.walk(dir_path):
            for filename in files:
                video_file_path = os.path.join(path, filename)
                if helper._check_if_valid_video(video_file_path):
                    list_of_videos_to_process.append(video_file_path)

        # Need to run in two sepearte loops to prevent recursion            
        for video_file_path in list_of_videos_to_process:
            statusI = self.compress_video(
                video_file_path,
                force_overwrite=force_overwrite,
                crf_parameter=crf_parameter,
                output_video_codec=output_video_codec,
                out_dir_path=out_dir_path,
            )
            status = bool(status and statusI)
        return status


    @FileDecorators.validate_file_path
    def save_frame_to_disk(self, frame, file_path, file_name, file_ext):
        """saves an in-memory numpy image array on drive.

        :param frame: In-memory image. This would have been generated by extract_video_keyframes method
        :type frame: numpy.ndarray, required
        :param file_name: name of the image.
        :type file_name: str, required
        :param file_path: Folder location where files needs to be saved
        :type file_path: str, required
        :param file_ext: File extension indicating the file type for example - '.jpg'
        :type file_ext: str, required
        :return: None
        """

        file_full_path = os.path.join(file_path, file_name + file_ext)
        cv2.imwrite(file_full_path, frame)

    @FileDecorators.validate_file_path
    def _split(self, file_path):
        """Function to split the videos and persist the chunks

        :param file_path: path of video file
        :type file_path: str, required
        :return: List of path of splitted video clips
        :rtype: list
        """
        clipped_files = []
        duration = self._get_video_duration_with_ffmpeg(file_path)
        # setting the start point to zero
        # Setting the breaking point for the clip to be 25 or if video is big
        # then relative to core available in the machine
        clip_start, break_point = (
            0,
            duration // cpu_count() if duration // cpu_count() > 15 else 25,
        )

        # Loop over the video duration to get the clip stating point and end point to split the video
        while clip_start < duration:

            clip_end = clip_start + break_point

            # Setting the end position of the particular clip equals to the end time of original clip,
            # if end position or end position added with the **min_video_duration** is greater than
            # the end time of original video
            if clip_end > duration or (clip_end + self.min_video_duration) > duration:
                clip_end = duration

            clipped_files.append(self._write_videofile(file_path, clip_start, clip_end))

            clip_start = clip_end
        return clipped_files

    def _write_videofile(self, video_file_path, start, end):
        """Function to clip the video for given start and end points and save the video

        :param video_file_path: path of video file
        :type video_file_path: str, required
        :param start: start time for clipping
        :type start: float, required
        :param end: end time for clipping
        :type end: float, required
        :return: path of splitted video clip
        :rtype: str
        """

        name = os.path.split(video_file_path)[1]

        # creating a unique name for the clip video
        # Naming Format: <video name>_<start position>_<end position>.mp4
        _clipped_file_path = os.path.join(
            self.temp_folder,
            "{0}_{1}_{2}.mp4".format(
                name.split(".")[0], int(1000 * start), int(1000 * end)
            ),
        )

        self._ffmpeg_extract_subclip(
            video_file_path, start, end, targetname=_clipped_file_path
        )
        return _clipped_file_path

    def _ffmpeg_extract_subclip(self, filename, t1, t2, targetname=None):
        """chops a new video clip from video file ``filename`` between
            the times ``t1`` and ``t2``, Uses ffmpy wrapper on top of ffmpeg
            library
        :param filename: path of video file
        :type filename: str, required
        :param t1: time from where video to clip
        :type t1: float, required
        :param t2: time to which video to clip
        :type t2: float, required
        :param targetname: path where clipped file to be stored
        :type targetname: str, optional
        :return: None
        """
        name, ext = os.path.splitext(filename)

        if not targetname:
            T1, T2 = [int(1000 * t) for t in [t1, t2]]
            targetname = name + "{0}SUB{1}_{2}.{3}".format(name, T1, T2, ext)

        timeParamter = "-ss " + "%0.2f" % t1 + " -t " + "%0.2f" % (t2 - t1)

        # Uses ffmpeg binary for video clipping using ffmpy wrapper
        FFMPEG_BINARY = os.getenv("FFMPEG_BINARY")
        ff = ffmpy.FFmpeg(
            executable=FFMPEG_BINARY,
            inputs={filename: "-y -hide_banner -loglevel panic "},
            outputs={targetname: timeParamter + " -vcodec copy -acodec copy"},
        )
        ff.run()

    @FileDecorators.validate_file_path
    def _get_video_duration_with_ffmpeg(self, file_path):
        """Get video duration using ffmpeg binary.
        Based on function ffmpeg_parse_infos inside repo
        https://github.com/Zulko/moviepy/moviepy/video/io/ffmpeg_reader.py
        The MIT License (MIT)
        Copyright (c) 2015 Zulko
        Returns a video duration in second

        :param file_path: video file path
        :type file_path: string
        :raises IOError:
        :return: duration of video clip in seconds
        :rtype: float
        """
        FFMPEG_BINARY = os.getenv("FFMPEG_BINARY")
        # Open the file in a pipe, read output
        ff = ffmpy.FFmpeg(
            executable=FFMPEG_BINARY,
            inputs={file_path: ""},
            outputs={None: "-f null -"},
        )
        _, error = ff.run(
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        infos = error.decode("utf8", errors="ignore")
        lines = infos.splitlines()
        if "No such file or directory" in lines[-1]:
            raise IOError(
                (
                    "Error: the file %s could not be found!\n"
                    "Please check that you entered the correct "
                    "path."
                )
                % file_path
            )

        # get duration (in seconds) by parsing ffmpeg file info returned by
        # ffmpeg binary
        video_duration = None
        decode_file = False
        try:
            if decode_file:
                line = [line for line in lines if "time=" in line][-1]
            else:
                line = [line for line in lines if "Duration:" in line][-1]
            match = re.findall("([0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9])", line)[0]
            video_duration = helper._convert_to_seconds(match)
        except Exception:
            raise IOError(
                f"error: failed to read the duration of file {file_path}.\n"
                f"Here are the file infos returned by ffmpeg:\n\n{infos}"
            )
        return video_duration
