"""
Feedback is public: everyone can read every item, upvote it and comment on it.
Only admins change the status. People can delete their own feedback and their
own comments; admins can delete any.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from database import get_db
from models import Feedback, FeedbackComment, FeedbackVote, FeedbackCommentVote, User
from schemas import FeedbackCreate, FeedbackUpdate, FeedbackOut, CommentCreate, CommentOut, VoteOut, FeedbackEdit
from models import _utcnow
from deps import get_current_user, is_admin
from typing import List

router = APIRouter(prefix="/feedback", tags=["feedback"])


def _feedback_out(items, db: Session, me: User):
    ids = [f.id for f in items]
    if not ids:
        return []
    votes = dict(db.query(FeedbackVote.feedback_id, func.count()).filter(FeedbackVote.feedback_id.in_(ids))
                 .group_by(FeedbackVote.feedback_id).all())
    mine = {fid for (fid,) in db.query(FeedbackVote.feedback_id)
            .filter(FeedbackVote.feedback_id.in_(ids), FeedbackVote.user_id == me.id).all()}
    comments = dict(db.query(FeedbackComment.feedback_id, func.count()).filter(FeedbackComment.feedback_id.in_(ids))
                    .group_by(FeedbackComment.feedback_id).all())
    out = []
    for f in items:
        d = FeedbackOut.model_validate(f).model_dump()
        d.update(vote_count=int(votes.get(f.id, 0)), voted=f.id in mine, comment_count=int(comments.get(f.id, 0)))
        out.append(d)
    return out


def _get_feedback(db: Session, feedback_id: int) -> Feedback:
    f = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not f:
        raise HTTPException(404, "Feedback not found")
    return f


@router.get("/", response_model=List[FeedbackOut])
def list_feedback(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Everyone sees all feedback."""
    items = db.query(Feedback).order_by(desc(Feedback.created_at)).all()
    return _feedback_out(items, db, current_user)


@router.post("/", response_model=FeedbackOut)
def create_feedback(body: FeedbackCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    f = Feedback(type=body.type, message=body.message, user_id=current_user.id)
    db.add(f); db.commit(); db.refresh(f)
    return _feedback_out([f], db, current_user)[0]


@router.patch("/{feedback_id}", response_model=FeedbackOut)
def update_feedback(feedback_id: int, body: FeedbackUpdate, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    """Admin only — update feedback status."""
    if not is_admin(current_user):
        raise HTTPException(403, "Admin access required")
    f = _get_feedback(db, feedback_id)
    f.status = body.status
    db.commit(); db.refresh(f)
    return _feedback_out([f], db, current_user)[0]


@router.put("/{feedback_id}", response_model=FeedbackOut)
def edit_feedback(feedback_id: int, body: FeedbackEdit, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    """Only the person who wrote it. The status is left as it is."""
    f = _get_feedback(db, feedback_id)
    if f.user_id != current_user.id:
        raise HTTPException(403, "You can only edit your own feedback")
    if not (body.message or "").split("||")[0].strip():
        raise HTTPException(400, "Feedback can't be empty")
    if body.type != f.type or body.message != f.message:
        f.type, f.message, f.edited_at = body.type, body.message, _utcnow()
        db.commit(); db.refresh(f)
    return _feedback_out([f], db, current_user)[0]


@router.delete("/{feedback_id}")
def delete_feedback(feedback_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The person who wrote it, or an admin. Removes its comments and votes too."""
    f = _get_feedback(db, feedback_id)
    if f.user_id != current_user.id and not is_admin(current_user):
        raise HTTPException(403, "You can only delete your own feedback")
    comment_ids = [c for (c,) in db.query(FeedbackComment.id).filter(FeedbackComment.feedback_id == f.id).all()]
    if comment_ids:
        db.query(FeedbackCommentVote).filter(FeedbackCommentVote.comment_id.in_(comment_ids)).delete(synchronize_session=False)
        db.query(FeedbackComment).filter(FeedbackComment.id.in_(comment_ids)).delete(synchronize_session=False)
    db.query(FeedbackVote).filter(FeedbackVote.feedback_id == f.id).delete(synchronize_session=False)
    db.delete(f); db.commit()
    return {"ok": True}


@router.post("/{feedback_id}/vote", response_model=VoteOut)
def toggle_vote(feedback_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Upvote, or take the upvote back if already given."""
    _get_feedback(db, feedback_id)
    v = db.query(FeedbackVote).filter(FeedbackVote.feedback_id == feedback_id, FeedbackVote.user_id == current_user.id).first()
    if v:
        db.delete(v)
    else:
        db.add(FeedbackVote(feedback_id=feedback_id, user_id=current_user.id))
    db.commit()
    n = db.query(func.count()).select_from(FeedbackVote).filter(FeedbackVote.feedback_id == feedback_id).scalar()
    return {"vote_count": int(n or 0), "voted": not v}


# ── Comments ──────────────────────────────────────────────────────────────────
def _comment_out(items, db: Session, me: User):
    ids = [c.id for c in items]
    if not ids:
        return []
    votes = dict(db.query(FeedbackCommentVote.comment_id, func.count()).filter(FeedbackCommentVote.comment_id.in_(ids))
                 .group_by(FeedbackCommentVote.comment_id).all())
    mine = {cid for (cid,) in db.query(FeedbackCommentVote.comment_id)
            .filter(FeedbackCommentVote.comment_id.in_(ids), FeedbackCommentVote.user_id == me.id).all()}
    out = []
    for c in items:
        d = CommentOut.model_validate(c).model_dump()
        d.update(vote_count=int(votes.get(c.id, 0)), voted=c.id in mine)
        out.append(d)
    return out


@router.get("/{feedback_id}/comments", response_model=List[CommentOut])
def list_comments(feedback_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _get_feedback(db, feedback_id)
    items = (db.query(FeedbackComment).filter(FeedbackComment.feedback_id == feedback_id)
             .order_by(FeedbackComment.created_at.asc(), FeedbackComment.id.asc()).all())
    return _comment_out(items, db, current_user)


@router.post("/{feedback_id}/comments", response_model=CommentOut)
def add_comment(feedback_id: int, body: CommentCreate, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    _get_feedback(db, feedback_id)
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(400, "Comment can't be empty")
    if len(text) > 4000:
        raise HTTPException(400, "Comment is too long (4,000 characters max)")
    c = FeedbackComment(feedback_id=feedback_id, user_id=current_user.id, message=text)
    db.add(c); db.commit(); db.refresh(c)
    return _comment_out([c], db, current_user)[0]


def _get_comment(db: Session, comment_id: int) -> FeedbackComment:
    c = db.query(FeedbackComment).filter(FeedbackComment.id == comment_id).first()
    if not c:
        raise HTTPException(404, "Comment not found")
    return c


@router.put("/comments/{comment_id}", response_model=CommentOut)
def edit_comment(comment_id: int, body: CommentCreate, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    """Only the person who wrote it."""
    c = _get_comment(db, comment_id)
    if c.user_id != current_user.id:
        raise HTTPException(403, "You can only edit your own comments")
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(400, "Comment can't be empty")
    if len(text) > 4000:
        raise HTTPException(400, "Comment is too long (4,000 characters max)")
    if text != c.message:
        c.message, c.edited_at = text, _utcnow()
        db.commit(); db.refresh(c)
    return _comment_out([c], db, current_user)[0]


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The person who wrote it, or an admin."""
    c = _get_comment(db, comment_id)
    if c.user_id != current_user.id and not is_admin(current_user):
        raise HTTPException(403, "You can only delete your own comments")
    db.query(FeedbackCommentVote).filter(FeedbackCommentVote.comment_id == c.id).delete(synchronize_session=False)
    db.delete(c); db.commit()
    return {"ok": True}


@router.post("/comments/{comment_id}/vote", response_model=VoteOut)
def toggle_comment_vote(comment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _get_comment(db, comment_id)
    v = (db.query(FeedbackCommentVote)
         .filter(FeedbackCommentVote.comment_id == comment_id, FeedbackCommentVote.user_id == current_user.id).first())
    if v:
        db.delete(v)
    else:
        db.add(FeedbackCommentVote(comment_id=comment_id, user_id=current_user.id))
    db.commit()
    n = db.query(func.count()).select_from(FeedbackCommentVote).filter(FeedbackCommentVote.comment_id == comment_id).scalar()
    return {"vote_count": int(n or 0), "voted": not v}