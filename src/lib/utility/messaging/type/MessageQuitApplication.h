#ifndef MESSAGE_QUIT_APPLICATION_H
#define MESSAGE_QUIT_APPLICATION_H

#include "Message.h"

class MessageQuitApplication: public Message<MessageQuitApplication>
{
public:
	explicit MessageQuitApplication(int exitCode = 0): exitCode(exitCode) {}

	const int exitCode;

	static const std::string getStaticType()
	{
		return "MessageQuitApplication";
	}
};

#endif	  // MESSAGE_QUIT_APPLICATION_H
