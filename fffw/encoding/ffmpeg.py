from itertools import chain

import fffw.graph.sources
from fffw.encoding import Muxer
from fffw.encoding import codec
from fffw.graph import FilterComplex, base
from fffw.wrapper import BaseWrapper, ensure_binary

__all__ = ['FFMPEG']


class InputList(list):
    def __call__(self):
        """ Delegates arguments formatting to Source objects."""
        result = []
        for src in self:
            if hasattr(src, 'get_args') and callable(src.get_args):
                result.extend(src.get_args())
            else:
                result.append(str(src))
        return result


class FFMPEG(BaseWrapper):
    command = 'ffmpeg'
    stderr_markers = ['[error]', '[fatal]']

    arguments = [
        ('loglevel', '-loglevel '),
        ('strict', '-strict '),
        ('realtime', '-re '),
        ('threads', '-threads '),
        ('time_offset', '-ss '),
        ('no_autorotate', '-noautorotate'),
        ('inputformat', '-f '),
        ('inputfile', '-i '),
        ('pix_fmt', '-pix_fmt '),
        ('presize_offset', '-ss '),
        ('filter_complex', '-filter_complex '),
        ('time_limit', '-t '),
        ('vframes', '-vframes '),
        ('overwrite', '-y '),
        ('verbose', '-v '),
        ('novideo', '-vn '),
        ('noaudio', '-an '),
        ('vfilter', '-vf '),
        ('afilter', '-af '),
        ('metadata', '-metadata '),
        ('map_chapters', '-map_chapters '),
        ('map_metadata', '-map_metadata '),
        ('vbsf', '-bsf:v '),
        ('absf', '-bsf:a '),
        ('format', '-f '),
        ('segment_list_flags', '-segment_list_flags '),
    ]

    def __init__(self, inputfile=None, **kw):
        super(FFMPEG, self).__init__(**kw)
        self._args['inputfile'] = self.__inputs = InputList()
        self.__outputs = []
        self.__vdest = self.__adest = 0

        self.__video = fffw.graph.sources.Input(kind=base.VIDEO)
        self.__audio = fffw.graph.sources.Input(kind=base.AUDIO)

        if isinstance(inputfile, fffw.graph.sources.BaseSource):
            self.add_input(inputfile)
        elif isinstance(inputfile, (list, tuple)):
            for i in inputfile:
                self.add_input(i)
        else:
            assert inputfile is None, "invalid inputfile type"

    def init_filter_complex(self):
        assert self.__inputs, "no inputs defined yet"
        assert not self.__outputs, "outputs already defined"
        self._args['filter_complex'] = fc = FilterComplex(
            video=self.__video,
            audio=self.__audio
        )
        return fc

    @property
    def filter_complex(self):
        """:rtype: FilterComplex"""
        return self._args['filter_complex']

    def get_args(self):
        return ensure_binary(
            [self.command] +
            super(FFMPEG, self).get_args() +
            self.get_output_args())

    def get_output_args(self):
        result = []
        for codecs, muxer in self.__outputs:
            args = list(chain.from_iterable(c.get_args() for c in codecs))
            result.extend(args + muxer.get_args() + [muxer.output])
        return result

    def add_input(self, inputfile):
        """ Adds new source file to ffmpeg.

        :type inputfile: graph.base.SourceFile
        """
        assert not self.filter_complex, "filter complex already initialized"
        assert isinstance(inputfile, fffw.graph.sources.BaseSource)
        self.__inputs.append(inputfile)

        for _ in range(inputfile.video_streams):
            i = len(self.__video.streams)
            self.__video < base.Source('%s:v' % i, base.VIDEO)
        if not inputfile.video_streams:
            self.__video < base.Source(None, base.VIDEO)

        for _ in range(inputfile.audio_streams):
            i = len(self.__audio.streams)
            self.__audio < base.Source('%s:a' % i, base.AUDIO)
        if not inputfile.audio_streams:
            self.__audio < base.Source(None, base.AUDIO)

    def add_output(self, muxer, *codecs):
        assert isinstance(muxer, Muxer)
        for c in codecs:
            assert isinstance(c, codec.BaseCodec)
            fc = self.filter_complex
            if not fc or getattr(c, 'map', None):
                # If filter_complex is not present or codec has source set,
                # connect codec to inputd directly.
                if c.codec_type == base.VIDEO:
                    self.__video | c
                if c.codec_type == base.AUDIO:
                    self.__audio | c
                continue
            if c.codec_type == base.VIDEO:
                try:
                    c.connect(
                        fc.get_video_dest(self.__vdest, create=False))
                    self.__vdest += 1
                except IndexError:
                    self.__video | c
            if c.codec_type == base.AUDIO:
                try:
                    c.connect(fc.get_audio_dest(self.__adest, create=False))
                    self.__adest += 1
                except IndexError:
                    self.__audio | c

        self.__outputs.append((codecs, muxer))

    @property
    def outputs(self):
        return list(self.__outputs)

    def __lt__(self, other):
        """ Adds new source file.

        :type other: graph.base.SourceFile
        """
        return self.add_input(other)

    def __setattr__(self, key, value):
        if key == 'filter_complex':
            raise NotImplementedError("use init_filter_complex instead")
        if key == 'inputfile':
            raise NotImplementedError("use add_input instead")
        return super(FFMPEG, self).__setattr__(key, value)

    def handle_stderr(self, line):
        """
        Handle ffmpeg output.

        Capture only lines containing one of `stderr_markers`
        """
        if not self.stderr_markers:
            # if no markers are defined, handle each line
            return super().handle_stderr(line)
        # capture only lines containing markers
        for marker in self.stderr_markers:
            if marker in line:
                super().handle_stderr(line)
