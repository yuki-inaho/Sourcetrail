#include "SourceChange.h"

#include <iostream>
#include <stdexcept>

int main()
{
	using namespace sourcetrail::core;
	try
	{
		const SourceContent empty {SourceContentStatus::Available, ""};
		const SourceContent before {SourceContentStatus::Available, "before\n"};
		const SourceContent after {SourceContentStatus::Available, "after\n"};
		std::size_t checked = 0;
		const auto check = [&checked](bool actual, bool expected) {
			++checked;
			if (actual != expected) throw std::runtime_error("INPUT-001 observation mismatch");
		};
		for (bool indexed: {false, true})
		{
			for (bool newer: {false, true})
			{
				check(didSourceChange(indexed, empty, empty, newer), false);
				check(didSourceChange(indexed, before, before, newer), false);
				check(didSourceChange(indexed, before, after, newer), true);
				check(didSourceChange(indexed, before, empty, newer), true);
				check(didSourceChange(indexed, empty, after, newer), true);
				for (const auto status: {SourceContentStatus::Missing, SourceContentStatus::Null,
					SourceContentStatus::ReadError})
				{
					const SourceContent unavailable {status, ""};
					check(didSourceChange(indexed, before, unavailable, newer), true);
					check(didSourceChange(indexed, unavailable, empty, newer),
						indexed || status != SourceContentStatus::Missing || newer);
				}
			}
		}
		std::cout << "INPUT-001: " << checked << " content, empty and failure observations passed\n";
		return 0;
	}
	catch (const std::exception& error)
	{
		std::cerr << error.what() << '\n';
		return 1;
	}
}
