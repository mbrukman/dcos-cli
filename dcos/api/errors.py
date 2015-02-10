import abc


class Error(object):
    """Abstract class for describing errors."""

    @abc.abstractmethod
    def error(self):
        """Creates an error message

        :returns: The error message
        :rtype: str
        """

        raise NotImplementedError


class DefaultError(Error):
    """Construct a basic Error class based on a string

    :param message: String to use for the error message
    :param type: str
    """

    def __init__(self, message):
        self._message = message

    def error(self):
        return self._message
