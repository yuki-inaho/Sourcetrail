#include "ExternalIndexerOutcome.h"

#include <algorithm>
#include <array>
#include <iostream>
#include <stdexcept>

namespace
{
void require(bool condition, const char* message)
{
	if (!condition)
	{
		throw std::runtime_error(message);
	}
}
}

int main()
{
	try
	{
		using sourcetrail::core::classifyExternalProcess;
		using sourcetrail::core::ExternalIndexerOutcome;
		using sourcetrail::core::ExternalProcessOutcome;

		for (int code: {-1, 0, 7})
		{
			require(classifyExternalProcess(true, code) == ExternalProcessOutcome::TransportError,
				"transport errors must not be lost, including a zero exit-code field");
			require(classifyExternalProcess(false, code) == (code == 0 ?
				ExternalProcessOutcome::Succeeded : ExternalProcessOutcome::NonzeroExit),
				"a completed process is classified by its exit code");
		}

		ExternalIndexerOutcome empty;
		require(empty.attempted == 0 && empty.settled == 0 && empty.succeeded == 0 &&
			empty.failed == 0 && empty.exitCode() == 0, "a run without external commands stays compatible");
		bool rejected = false;
		try
		{
			empty.settleCommand(ExternalProcessOutcome::Succeeded);
		}
		catch (const std::logic_error&)
		{
			rejected = true;
		}
		require(rejected && empty.settled == 0, "settling before starting must be rejected");

		const std::array<ExternalProcessOutcome, 3> outcomes {{ExternalProcessOutcome::Succeeded,
			ExternalProcessOutcome::TransportError, ExternalProcessOutcome::NonzeroExit}};
		std::size_t cases = 0;
		for (int a = 0; a < 3; ++a)
		{
			for (int b = 0; b < 3; ++b)
			{
				for (int c = 0; c < 3; ++c)
				{
					const std::array<int, 3> results {{a, b, c}};
					std::array<int, 3> order {{0, 1, 2}};
					do
					{
						ExternalIndexerOutcome run;
						for (int i = 0; i < 3; ++i)
						{
							run.beginCommand();
						}
						std::size_t expectedFailures = 0;
						std::size_t completed = 0;
						for (int index: order)
						{
							// The expected count comes from the authored outcome labels,
							// not from the production classifier or aggregation methods.
							expectedFailures += results[index] != 0;
							++completed;
							run.settleCommand(outcomes[results[index]]);
							require(run.attempted == 3 && run.settled == completed &&
								run.failed == expectedFailures &&
								run.succeeded == completed - expectedFailures &&
								run.hasFailure() == (expectedFailures != 0),
								"completion order must preserve counts and every failure");
						}
						require(run.exitCode() == (expectedFailures != 0 ? 1 : 0),
							"the terminal status must represent the whole run");
						++cases;
					} while (std::next_permutation(order.begin(), order.end()));
				}
			}
		}
		require(cases == 162, "all declared outcome/completion-order combinations must run");

		ExternalIndexerOutcome sequential;
		sequential.beginCommand();
		sequential.settleCommand(ExternalProcessOutcome::NonzeroExit);
		sequential.beginCommand();
		require(sequential.attempted == 2 && sequential.settled == 1 && sequential.hasFailure(),
			"starting another command cannot erase a previous failure");
		sequential.settleCommand(ExternalProcessOutcome::Succeeded);
		require(sequential.exitCode() == 1 && sequential.succeeded == 1 && sequential.failed == 1,
			"later success cannot turn a failed run into success");

		ExternalIndexerOutcome invalid;
		invalid.beginCommand();
		rejected = false;
		try
		{
			invalid.settleCommand(static_cast<ExternalProcessOutcome>(99));
		}
		catch (const std::invalid_argument&)
		{
			rejected = true;
		}
		require(rejected && invalid.settled == 0 && invalid.failed == 0 && invalid.succeeded == 0,
			"unknown outcomes must be rejected without changing the observation");
		std::cout << "EXECUTION-001: classification matrix, 162 completion orders and lifecycle controls passed\n";
		return 0;
	}
	catch (const std::exception& error)
	{
		std::cerr << error.what() << '\n';
		return 1;
	}
}
