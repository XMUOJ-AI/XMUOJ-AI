from rest_framework.parsers import JSONParser
from utils.contract_api import ContractAPIView, idempotency_key
from . import services


class AgentView(ContractAPIView):
    error_prefix = "AGENT"
    parser_classes = (JSONParser,)


class ConversationView(AgentView):
    def post(self, request):
        conversation, created = services.start_conversation(request.user, request.data)
        return self.success(services.conversation_data(conversation), 201 if created else 200)


class RunsView(AgentView):
    def post(self, request):
        key = idempotency_key(request, "AGENT_INPUT_INVALID")
        run, created = services.create_run(request.user, request.data, key)
        return self.success(services.run_data(run), 202 if created else 200)


class RunView(AgentView):
    def get(self, request, run_id):
        return self.success(services.run_data(services.authorize_run(request.user, run_id)))


class FeedbackView(AgentView):
    def post(self, request, run_id):
        return self.success(services.feedback(request.user, run_id, request.data))
