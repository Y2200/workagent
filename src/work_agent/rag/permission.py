class PermissionFilter:


    def filter(
            self,
            documents,
            user_context
    ):

        if not user_context:
            return documents


        return [
            doc
            for doc in documents
            if self.check(
                doc,
                user_context
            )
        ]



    @staticmethod
    def check(
            item,
            user_context
    ):

        metadata = item.get(
            "metadata",
            {}
        )


        access = metadata.get(
            "access",
            {}
        )


        departments = access.get(
            "departments",
            []
        )


        roles = access.get(
            "roles",
            []
        )


        user_ids = access.get(
            "user_ids",
            []
        )


        department = user_context.get(
            "department"
        )


        role = user_context.get(
            "role"
        )


        user_id = user_context.get(
            "user_id"
        )


        if "ALL" in departments:
            return True


        if department in departments:
            return True


        if role in roles:
            return True


        # 指定用户授权
        if user_id is not None:

            user_ids_set = {
                int(uid)
                for uid in user_ids
                if uid is not None
            }

            if int(user_id) in user_ids_set:
                return True


        return False