#include "TextAccess.h"

#include <fstream>

#include "logging.h"

std::shared_ptr<TextAccess> TextAccess::createFromFile(const FilePath& filePath)
{
	std::shared_ptr<TextAccess> result = tryCreateFromFile(filePath);
	return result ? result : createFromString("", filePath);
}

std::shared_ptr<TextAccess> TextAccess::tryCreateFromFile(const FilePath& filePath)
{
	try
	{
		std::ifstream input(filePath.str(), std::ios::binary | std::ios::in);
		if (!input.is_open())
		{
			LOG_ERROR(L"Could not open file " + filePath.wstr());
			return nullptr;
		}
		std::string raw;
		char buffer[8192];
		while (input.read(buffer, sizeof(buffer)) || input.gcount())
		{
			raw.append(buffer, static_cast<size_t>(input.gcount()));
		}
		if (input.bad() || !input.eof())
		{
			LOG_ERROR(L"Could not completely read file " + filePath.wstr());
			return nullptr;
		}
		// The display/storage convention is LF. Preserve whether the source has
		// a final newline; never turn a failed read into successful empty content.
		std::string text;
		text.reserve(raw.size());
		for (size_t i = 0; i < raw.size(); ++i)
		{
			if (raw[i] == '\r')
			{
				if (i + 1 < raw.size() && raw[i + 1] == '\n')
				{
					++i;
				}
				text += '\n';
			}
			else
			{
				text += raw[i];
			}
		}
		return createFromString(text, filePath);
	}
	catch (const std::exception& error)
	{
		LOG_ERROR_STREAM(<< "Could not read " << filePath.str() << ": " << error.what());
		return nullptr;
	}
}

std::shared_ptr<TextAccess> TextAccess::createFromString(const std::string& text, const FilePath& filePath)
{
	std::shared_ptr<TextAccess> result(new TextAccess());

	result->m_lines = splitStringByLines(text);
	result->m_filePath = filePath;

	return result;
}

std::shared_ptr<TextAccess> TextAccess::createFromLines(
	const std::vector<std::string>& lines, const FilePath& filePath)
{
	std::shared_ptr<TextAccess> result(new TextAccess());

	result->m_lines = lines;
	result->m_filePath = filePath;

	return result;
}

unsigned int TextAccess::getLineCount() const
{
	return static_cast<unsigned int>(m_lines.size());
}

bool TextAccess::isEmpty() const
{
	return m_lines.empty();
}

FilePath TextAccess::getFilePath() const
{
	return m_filePath;
}

std::string TextAccess::getLine(const unsigned int lineNumber) const
{
	if (!checkIndexInRange(lineNumber))
	{
		return "";
	}

	return m_lines[lineNumber - 1];	   // -1 to correct for use as index
}

std::vector<std::string> TextAccess::getLines(
	const unsigned int firstLineNumber, const unsigned int lastLineNumber)
{
	if (!checkIndexIntervalInRange(firstLineNumber, lastLineNumber))
	{
		return std::vector<std::string>();
	}

	std::vector<std::string>::iterator first = m_lines.begin() + firstLineNumber -
		1;	  // -1 to correct for use as index
	std::vector<std::string>::iterator last = m_lines.begin() + lastLineNumber;
	return std::vector<std::string>(first, last);
}

const std::vector<std::string>& TextAccess::getAllLines() const
{
	return m_lines;
}

std::string TextAccess::getText() const
{
	std::string result = "";

	for (unsigned int i = 0; i < m_lines.size(); i++)
	{
		result += m_lines[i];
	}

	return result;
}

std::vector<std::string> TextAccess::splitStringByLines(const std::string& text)
{
	std::vector<std::string> result;
	size_t prevIndex = 0;
	size_t index = text.find('\n');

	while (index != std::string::npos)
	{
		result.push_back(text.substr(prevIndex, index - prevIndex) + '\n');

		prevIndex = index + 1;
		index = text.find('\n', prevIndex);
	}

	if (prevIndex < text.length())
	{
		result.push_back(text.substr(prevIndex));
	}

	return result;
}

TextAccess::TextAccess(): m_filePath(L"") {}

bool TextAccess::checkIndexInRange(const unsigned int index) const
{
	if (index < 1)
	{
		LOG_WARNING_STREAM(<< "Line numbers start with one, is " << index);
		return false;
	}
	else if (index > m_lines.size())
	{
		LOG_WARNING_STREAM(
			<< "Tried to access index " << index << ". Maximum index is " << m_lines.size());
		return false;
	}

	return true;
}

bool TextAccess::checkIndexIntervalInRange(const unsigned int firstIndex, const unsigned int lastIndex) const
{
	if (!checkIndexInRange(firstIndex) || !checkIndexInRange(lastIndex))
	{
		return false;
	}
	else if (firstIndex > lastIndex)
	{
		LOG_WARNING_STREAM(
			<< "Index 'firstLine' has to be lower or equal index 'lastLine', is " << firstIndex
			<< " > " << lastIndex);
		return false;
	}

	return true;
}
