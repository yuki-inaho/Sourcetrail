#ifndef SOURCETRAIL_CORE_UTF8_SOURCE_LOCATION_MAP_H
#define SOURCETRAIL_CORE_UTF8_SOURCE_LOCATION_MAP_H

#include <cstddef>
#include <stdexcept>
#include <string>
#include <vector>

namespace sourcetrail
{
namespace core
{

struct SourceRange
{
	std::size_t startLine;
	std::size_t startColumn;
	std::size_t endLine;
	std::size_t endColumn;
};

// Pure conversion for the legacy Python parser's Unicode-scalar columns.
// Both input and output use one-based lines and inclusive columns. A UTF-8 BOM
// is invisible to the parser but remains part of the stored first line.
class Utf8SourceLocationMap
{
public:
	explicit Utf8SourceLocationMap(const std::string& source)
	{
		std::size_t begin = 0;
		do
		{
			const std::size_t newline = source.find('\n', begin);
			const std::size_t end = newline == std::string::npos ? source.size() : newline;
			Line line;
			std::size_t cursor = begin;
			if (begin == 0 && source.compare(0, 3, "\xef\xbb\xbf") == 0)
			{
				cursor += 3;
			}
			line.boundaries.push_back(cursor - begin);
			while (cursor < end)
			{
				cursor += scalarWidth(source, cursor, end);
				line.boundaries.push_back(cursor - begin);
			}
			m_lines.push_back(line);
			if (newline == std::string::npos || newline + 1 == source.size())
			{
				break;
			}
			begin = newline + 1;
		} while (begin < source.size());
	}

	SourceRange toBytes(SourceRange input, bool allowEmptyBoundary = false) const
	{
		const Line& first = line(input.startLine);
		if (input.startColumn == 0 || input.startColumn > first.boundaries.size())
		{
			throw std::invalid_argument("Python source start column is outside its stored line");
		}
		// Parso scopes end at (next line, 0), including when it appended its
		// synthetic final newline. The stored range ends on the preceding line.
		if (input.endColumn == 0 && input.endLine > input.startLine)
		{
			if (!allowEmptyBoundary)
			{
				throw std::invalid_argument("Only scope or diagnostic ranges may end at a line boundary");
			}
			--input.endLine;
			const Line& last = line(input.endLine);
			input.endColumn = last.boundaries.size() - 1;
		}
		const Line& last = line(input.endLine);
		if (input.endLine < input.startLine || input.endColumn >= last.boundaries.size())
		{
			throw std::invalid_argument("Python source end position is outside its stored line");
		}
		SourceRange result {input.startLine, first.boundaries[input.startColumn - 1] + 1,
			input.endLine, last.boundaries[input.endColumn]};
		if (input.endLine == input.startLine && input.endColumn + 1 == input.startColumn)
		{
			if (!allowEmptyBoundary)
			{
				throw std::invalid_argument("A token location cannot be empty");
			}
			result.endColumn = result.startColumn;
		}
		else if (input.endLine == input.startLine && input.endColumn < input.startColumn)
		{
			throw std::invalid_argument("Python source range is reversed");
		}
		else if (result.endColumn == 0)
		{
			// An empty final line has a single representable boundary at column 1.
			result.endColumn = 1;
		}
		return result;
	}

private:
	struct Line
	{
		std::vector<std::size_t> boundaries;
	};

	const Line& line(std::size_t number) const
	{
		if (number == 0 || number > m_lines.size())
		{
			throw std::invalid_argument("Python source line is outside stored content");
		}
		return m_lines[number - 1];
	}

	static std::size_t scalarWidth(const std::string& source, std::size_t at, std::size_t end)
	{
		const unsigned char lead = static_cast<unsigned char>(source[at]);
		if (lead == 0 || lead == '\r')
		{
			throw std::invalid_argument("Python stored content contains NUL or unnormalised CR");
		}
		if (lead < 0x80)
		{
			return 1;
		}
		const std::size_t width = lead >= 0xc2 && lead <= 0xdf ? 2 :
			(lead >= 0xe0 && lead <= 0xef ? 3 : (lead >= 0xf0 && lead <= 0xf4 ? 4 : 0));
		if (width == 0 || at + width > end)
		{
			throw std::invalid_argument("Invalid UTF-8 in Python stored content");
		}
		for (std::size_t i = 1; i < width; ++i)
		{
			const unsigned char value = static_cast<unsigned char>(source[at + i]);
			if ((value & 0xc0) != 0x80)
			{
				throw std::invalid_argument("Invalid UTF-8 continuation byte");
			}
		}
		const unsigned char second = static_cast<unsigned char>(source[at + 1]);
		if ((lead == 0xe0 && second < 0xa0) || (lead == 0xed && second >= 0xa0) ||
			(lead == 0xf0 && second < 0x90) || (lead == 0xf4 && second >= 0x90))
		{
			throw std::invalid_argument("UTF-8 scalar is overlong, a surrogate, or out of range");
		}
		return width;
	}

	std::vector<Line> m_lines;
};

} // namespace core
} // namespace sourcetrail

#endif // SOURCETRAIL_CORE_UTF8_SOURCE_LOCATION_MAP_H
