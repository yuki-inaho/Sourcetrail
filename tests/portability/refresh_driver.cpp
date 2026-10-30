#include "RefreshPlanner.h"

#include <array>
#include <cstdint>
#include <iostream>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>

namespace
{
using Files = std::set<unsigned int>;

std::uint64_t parseMask(const std::string& token)
{
	if (token.empty() || token.find_first_not_of("0123456789") != std::string::npos)
	{
		throw std::runtime_error("expected an unsigned decimal mask");
	}
	return std::stoull(token);
}

Files files(std::uint64_t mask)
{
	Files result;
	for (unsigned int file = 0; file < 64; ++file)
	{
		if (mask & (UINT64_C(1) << file))
		{
			result.insert(file);
		}
	}
	return result;
}

std::uint64_t mask(const Files& files)
{
	std::uint64_t result = 0;
	for (unsigned int file: files)
	{
		if (file >= 64)
		{
			throw std::runtime_error("output identity is outside the transport domain");
		}
		result |= UINT64_C(1) << file;
	}
	return result;
}
} // namespace

int main(int argc, char**)
{
	std::size_t lineNumber = 0;
	try
	{
		if (argc != 1)
		{
			throw std::runtime_error("refresh driver accepts input on stdin, without arguments");
		}
		std::string line;
		while (std::getline(std::cin, line))
		{
			++lineNumber;
			std::istringstream row(line);
			std::array<Files, 6> inputs;
			for (Files& input: inputs)
			{
				std::string token;
				if (!(row >> token))
				{
					throw std::runtime_error("expected exactly six masks");
				}
				input = files(parseMask(token));
			}
			std::string extra;
			if (row >> extra)
			{
				throw std::runtime_error("expected exactly six masks");
			}
			const auto selection = sourcetrail::core::prepareUpdatedRefresh(
				inputs[0], inputs[2], inputs[3]);
			const auto result = sourcetrail::core::finishUpdatedRefresh(
				inputs[0], inputs[1], selection, inputs[4], inputs[5]);
			std::cout << mask(selection.initialFilesToClear) << ' '
				<< mask(selection.staticSourceFiles) << ' ' << mask(result.filesToClear) << ' '
				<< mask(result.filesToIndex) << '\n';
		}
		if (lineNumber == 0 || std::cin.bad())
		{
			throw std::runtime_error("input must contain at least one complete case");
		}
		return 0;
	}
	catch (const std::exception& error)
	{
		std::cerr << "line " << lineNumber << ": " << error.what() << '\n';
		return 2;
	}
}
