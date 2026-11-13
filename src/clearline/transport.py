"""Narrow provider boundary. Only the local simulator is implemented."""
from typing import Protocol

class MessageProvider(Protocol):
    def send_approved(self,job:dict,followup_days:int=7)->None: ...
    def ingest(self,account_id:str,reply_to:str,message_id:str,body:str)->dict: ...
    def conversation(self,account_id:str)->dict: ...

class SimulatedProvider:
    def __init__(self,store):self.store=store
    def send_approved(self,job,followup_days=7):
        # Approval/hash verification and persistence remain one SQLite transaction.
        self.store._deliver_simulated(job,followup_days)
    def ingest(self,account_id,reply_to,message_id,body):
        from .conversations import ingest_message
        return ingest_message(self.store,account_id,reply_to,message_id,body)
    def conversation(self,account_id):
        from .conversations import conversation
        return conversation(self.store,account_id)
